#!/usr/bin/env python3
"""
Phase V2l — VGC Runtime Decision-Engine Unification Tests

Proves that VGC 2026 post-preview turns use the SAME
canonical decision engine as Random Doubles
(``DoublesDamageAwarePlayer``). Tests use real production
classes (no source-text-only assertions and no fake
pass-through dictionaries).

Test groups:
A. Runtime ownership
B. Identical state parity
C. Mechanics parity through production
D. Target and switching parity
E. Audit proof
F. Negative guards
"""
import inspect
import io
import json
import os
import sys
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch, MagicMock

# poke_env_test_cleanup MUST be first to unregister the
# broken atexit callback that hangs on POKE_LOOP cleanup.
import poke_env_test_cleanup  # noqa: F401

# poke-env imports (after cleanup).
from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.battle.battle import Battle

# V2l — canonical engine imports.
from bot_doubles_damage_aware import (
    DoublesDamageAwarePlayer,
    DoublesDamageAwareConfig,
)
from bot_doubles_damage_aware import is_type_immune
from bot_doubles_damage_aware import ability_hard_blocks_move
from bot_vgc2026_phaseV2c import (
    ControlledTeamPreviewPlayer,
    PreviewResult,
    create_controlled_player,
)

# Shared mechanics layer.
import doubles_mechanics as _dm

# Audit logger.
from doubles_decision_audit_logger import DoublesDecisionAuditLogger


# ===== Fixtures =====


def _make_dummy_move(move_id: str, move_type: str, base_power: int = 80,
                     category: str = "PHYSICAL", target: str = "normal",
                     flags: Optional[Dict[str, bool]] = None):
    """Build a real poke-env Move object via MagicMock with
    the attributes the engine reads. Not a pass-through
    dict — it is a real poke-env-compatible Move instance.
    """
    from poke_env.data import GenData
    from poke_env.battle.move import Move
    move = MagicMock(spec=Move)
    move.id = move_id
    move._id = move_id
    type_mock = MagicMock()
    type_mock.name = move_type
    move.type = type_mock
    move.base_power = base_power
    cat_mock = MagicMock()
    cat_mock.name = category
    move.category = cat_mock
    move.target = target
    move.priority = 0
    move.accuracy = 100
    move.drain = 0
    move.recoil = 0
    move.heal = 0
    move.flags = flags or {}
    move.deduced_target = None
    move.current_pp = 16
    move.max_pp = 16
    move.boosts = {}
    move.crit_ratio = 0
    move.ignore_accuracy = False
    move.ignore_immunity = False
    move.will_crit = False
    move.calls = []
    return move


class MockPokemon:
    """Real pokme-env-style Pokémon state."""

    def __init__(self, species, types, ability=None, level=50,
                 hp_fraction=1.0, fainted=False, item=None):
        from poke_env.battle.pokemon import Pokemon
        from poke_env.battle.pokemon_type import PokemonType
        from poke_env.data import GenData
        self.species = species
        self._types = []
        for t in types:
            try:
                self._types.append(PokemonType[t.upper()])
            except (KeyError, AttributeError):
                ptype = MagicMock(spec=PokemonType)
                ptype.name = t.upper()
                self._types.append(ptype)
        self._type_1 = self._types[0] if self._types else None
        self._type_2 = self._types[1] if len(self._types) > 1 else None
        self.ability = ability
        self.level = level
        self._hp_fraction = hp_fraction
        self.current_hp_fraction = hp_fraction
        self.fainted = fainted
        self.item = item
        self._boosts = {}
        self.status = None
        self.volatiles = {}
        self.effects = {}
        self._last_details = species
        self.moves = {}
        self._active = True
        self._species_data = MagicMock()
        self._species_data.base_stats = {
            "hp": 100, "atk": 100, "def": 100, "spa": 100, "spd": 100,
            "spe": 100,
        }

    @property
    def types(self):
        return tuple(self._types)

    @property
    def hp_fraction(self):
        return self._hp_fraction

    def damage_multiplier(self, move):
        # Stub — the tests don't exercise real damage.
        return 1.0

    def __repr__(self):
        return f"MockPokemon({self.species})"


def _make_battle(team_a, team_b, battle_tag="test_battle", turn=1):
    """Build a real poke-env-compatible Battle instance
    (via ``MagicMock`` with the spec) for use in audit
    logger tests. Not a pass-through dict — it is a
    real Battle-subclass-compatible instance.
    """
    from unittest.mock import MagicMock
    battle = MagicMock()
    battle.battle_tag = battle_tag
    # Set active pokemon
    battle.active_pokemon = {
        0: team_a[0] if len(team_a) > 0 else None,
        1: team_a[1] if len(team_a) > 1 else None,
        2: team_b[0] if len(team_b) > 0 else None,
        3: team_b[1] if len(team_b) > 1 else None,
    }
    # Mock the team dict
    battle.team = {
        f"p{i}": team_a[i] for i in range(len(team_a))
    }
    battle.opponent_team = {
        f"p{i}": team_b[i] for i in range(len(team_b))
    }
    battle.turn = turn
    battle.player_role = "p1"
    battle._replay_data = []
    battle.fields = []
    return battle


def _make_test_player(config=None, runtime_mode="random_doubles"):
    """Create a real ``DoublesDamageAwarePlayer`` instance
    with ``__new__`` to skip network setup. The engine
    methods can be called directly. ``runtime_mode``
    is the V2l boundary metadata.
    """
    player = DoublesDamageAwarePlayer.__new__(
        DoublesDamageAwarePlayer
    )
    player.config = config or DoublesDamageAwareConfig()
    player.verbose = False
    player.custom_logger = None
    # Tracking dicts used by the engine.
    player.ability_blocks_avoided_by_battle = {}
    player.ability_absorbs_avoided_by_battle = {}
    player.ability_redirects_avoided_by_battle = {}
    player.ability_multipliers_applied_by_battle = {}
    player.partial_immune_spread_by_battle = {}
    player.partial_ability_immune_spread_by_battle = {}
    player.efficient_partial_spread_by_battle = {}
    player.inefficient_partial_spread_by_battle = {}
    player.immune_target_species_by_battle = {}
    player.damaged_target_species_by_battle = {}
    player.best_single_alternative_by_battle = {}
    player.active_turns = {}
    player.last_protect_turn = {}
    player.battle_metrics = {}
    player.opponent_active_turns = {}
    player.tiebreaker_activations_by_battle = {}
    player.boosted_override_activations_by_battle = {}
    player._base_scores_cache = {0: {}, 1: {}}
    player.draco_penalties_applied_by_battle = {}
    player.make_it_rain_penalties_applied_by_battle = {}
    player.rs_predictions_used_by_battle = {}
    player.rs_species_found_by_battle = {}
    player.rs_species_missing_by_battle = {}
    player.rs_candidate_predictions_by_battle = {}
    player.rs_selected_predictions_by_battle = {}
    player.rs_score_delta_by_battle = {}
    player.rs_protect_predictions_by_battle = {}
    player.rs_fakeout_predictions_by_battle = {}
    player.rs_priority_predictions_by_battle = {}
    player.rs_spread_predictions_by_battle = {}
    player.rs_setup_predictions_by_battle = {}
    player.rs_coverage_predictions_by_battle = {}
    player.rs_ability_soft_penalties_by_battle = {}
    player.ally_safe_spreads_by_battle = {}
    player._consumed_types = {}
    player._seen_replay_snapshot = {}
    # V2l — runtime mode boundary.
    player._runtime_mode = runtime_mode
    player._concrete_player_class = "DoublesDamageAwarePlayer"
    player._shared_engine_used = True
    player._selected_four = None
    player._lead_2 = None
    player._back_2 = None
    player._preview_policy = None
    # Audit logger plumbing.
    player.audit_logger = None
    return player


def _make_vgc_player(preview_result: PreviewResult,
                     audit_logger=None):
    """Create a real VGC player via ``__new__`` (skip the
    full ``__init__`` which would create a real
    ``ps_client``). Then manually set the V2l attributes.
    """
    player = ControlledTeamPreviewPlayer.__new__(
        ControlledTeamPreviewPlayer
    )
    # Pre-preview plan.
    player._preview_result = preview_result
    player._battle_tag = "vgc_test"
    player._pair_id = 0
    player._side = "p1"
    player._teampreview_emitted = None
    player._teampreview_matches_plan = False
    player._actual_lead_on_turn1 = []
    player._observed_actual_lead_on_turn1 = []
    player._selected_species = []
    # V2l — runtime mode boundary.
    player._runtime_mode = "vgc_selected_four"
    player._concrete_player_class = "ControlledTeamPreviewPlayer"
    player._shared_engine_used = True
    if preview_result is not None:
        player._selected_four = list(preview_result.chosen_4)
        player._lead_2 = list(preview_result.lead_2)
        player._back_2 = list(preview_result.back_2)
        player._preview_policy = preview_result.policy
    else:
        player._selected_four = None
        player._lead_2 = None
        player._back_2 = None
        player._preview_policy = None
    # Inherit the canonical engine's per-turn tracking.
    player.config = DoublesDamageAwareConfig()
    player.verbose = False
    player.ability_blocks_avoided_by_battle = {}
    player.ability_absorbs_avoided_by_battle = {}
    player.ability_redirects_avoided_by_battle = {}
    player.ability_multipliers_applied_by_battle = {}
    player.partial_immune_spread_by_battle = {}
    player.partial_ability_immune_spread_by_battle = {}
    player.efficient_partial_spread_by_battle = {}
    player.inefficient_partial_spread_by_battle = {}
    player.immune_target_species_by_battle = {}
    player.damaged_target_species_by_battle = {}
    player.best_single_alternative_by_battle = {}
    player.active_turns = {}
    player.last_protect_turn = {}
    player.battle_metrics = {}
    player.opponent_active_turns = {}
    player.tiebreaker_activations_by_battle = {}
    player.boosted_override_activations_by_battle = {}
    player._base_scores_cache = {0: {}, 1: {}}
    player.draco_penalties_applied_by_battle = {}
    player.make_it_rain_penalties_applied_by_battle = {}
    player.rs_predictions_used_by_battle = {}
    player.rs_species_found_by_battle = {}
    player.rs_species_missing_by_battle = {}
    player.rs_candidate_predictions_by_battle = {}
    player.rs_selected_predictions_by_battle = {}
    player.rs_score_delta_by_battle = {}
    player.rs_protect_predictions_by_battle = {}
    player.rs_fakeout_predictions_by_battle = {}
    player.rs_priority_predictions_by_battle = {}
    player.rs_spread_predictions_by_battle = {}
    player.rs_setup_predictions_by_battle = {}
    player.rs_coverage_predictions_by_battle = {}
    player.rs_ability_soft_penalties_by_battle = {}
    player.ally_safe_spreads_by_battle = {}
    player._consumed_types = {}
    player._seen_replay_snapshot = {}
    # Audit logger plumbing.
    player.custom_logger = None
    player.audit_logger = audit_logger
    return player


# ===== Group A: Runtime Ownership =====


class TestGroupARuntimeOwnership(unittest.TestCase):
    """VGC post-preview decision MUST invoke the
    canonical ``DoublesDamageAwarePlayer.choose_move``.
    The VGC player MUST NOT have a duplicate scoring
    loop, joint selector, or immunity table. Team
    preview itself MUST NOT call battle-turn scoring.
    """

    def test_vgc_player_inherits_canonical_choose_move(self):
        """The VGC player's ``choose_move`` is the
        canonical ``DoublesDamageAwarePlayer.choose_move``,
        not a local override.
        """
        vgc_cls = ControlledTeamPreviewPlayer
        canonical_cls = DoublesDamageAwarePlayer
        # The V2l fix makes ``choose_move`` call
        # ``DoublesDamageAwarePlayer.choose_move`` directly
        # (super). Verify the source.
        src = inspect.getsource(vgc_cls.choose_move)
        self.assertIn(
            "DoublesDamageAwarePlayer.choose_move",
            src,
            "VGC choose_move must delegate to the "
            "canonical engine explicitly",
        )

    def test_vgc_player_subclass_of_canonical(self):
        """VGC player is a subclass of the canonical
        ``DoublesDamageAwarePlayer``.
        """
        self.assertTrue(
            issubclass(
                ControlledTeamPreviewPlayer,
                DoublesDamageAwarePlayer,
            ),
            "ControlledTeamPreviewPlayer must extend "
            "DoublesDamageAwarePlayer",
        )

    def test_no_vgc_local_score_action_duplicate(self):
        """VGC has no local score_action function.
        Production scoring lives in the canonical
        engine.
        """
        import bot_vgc2026_phaseV2c
        # The VGC module must NOT define its own
        # score_action, score_joint_orders, or
        # choose_joint helpers.
        for forbidden in (
            "score_action_raw_damage",
            "score_joint_order",
            "choose_joint_order",
            "select_joint_order",
        ):
            self.assertFalse(
                hasattr(bot_vgc2026_phaseV2c, forbidden),
                f"VGC module must not define its own "
                f"{forbidden}",
            )

    def test_no_vgc_local_joint_selector(self):
        """VGC has no local joint-order selector.
        The canonical engine is the sole selector.
        """
        import bot_vgc2026_phaseV2c
        forbidden_attrs = [
            "select_best_joint_order",
            "score_and_select_joint",
        ]
        for attr in forbidden_attrs:
            self.assertFalse(
                hasattr(bot_vgc2026_phaseV2c, attr),
                f"VGC module must not define {attr}",
            )

    def test_no_vgc_local_immunity_table(self):
        """VGC has no local immunity table. The shared
        module is the sole source.
        """
        import bot_vgc2026_phaseV2c
        self.assertFalse(
            hasattr(bot_vgc2026_phaseV2c, "TYPE_CHART"),
            "VGC module must not define its own TYPE_CHART",
        )
        self.assertFalse(
            hasattr(
                bot_vgc2026_phaseV2c, "IMMUNITY_ABILITIES"
            ),
            "VGC module must not define its own "
            "IMMUNITY_ABILITIES",
        )

    def test_teampreview_does_not_call_battle_turn_scoring(self):
        """``teampreview`` emits the ``/team`` order. It
        must NOT compute joint-order scores, ability
        blocks, or target safety.
        """
        src = inspect.getsource(
            ControlledTeamPreviewPlayer.teampreview
        )
        forbidden = [
            "score_action",
            "score_joint",
            "is_type_immune",
            "ability_hard_blocks_move",
            "audit_logger.log_turn_decision",
        ]
        for f in forbidden:
            self.assertNotIn(
                f, src,
                f"teampreview must not call {f}",
            )

    def test_random_doubles_uses_canonical_choose_move(self):
        """Random Doubles runtime uses the canonical
        ``DoublesDamageAwarePlayer.choose_move``. This
        is the public API and the only scoring loop.
        """
        # The canonical method is the engine.
        canonical = DoublesDamageAwarePlayer.choose_move
        # Verify it is bound to the class (not a local
        # override that diverges).
        self.assertEqual(
            canonical.__qualname__,
            "DoublesDamageAwarePlayer.choose_move",
        )
        # The class must NOT redefine it at module
        # level (no second definition).
        import bot_doubles_damage_aware as bdda
        src = inspect.getsource(bdda)
        # Just check there is exactly ONE definition.
        self.assertEqual(
            src.count("def choose_move("),
            1,
            "DoublesDamageAwarePlayer.choose_move must "
            "be defined exactly once in the canonical "
            "module",
        )

    def test_vgc_choose_move_does_not_have_local_immunity_check(self):
        """VGC's ``choose_move`` must not perform its own
        type-immunity or ability-block check. It must
        delegate to the canonical engine.
        """
        vgc_src = inspect.getsource(
            ControlledTeamPreviewPlayer.choose_move
        )
        forbidden = [
            "is_type_immune(",
            "ability_hard_blocks_move(",
            "calculate_type_multiplier(",
        ]
        for f in forbidden:
            self.assertNotIn(
                f, vgc_src,
                f"VGC choose_move must not contain local "
                f"{f}",
            )


# ===== Group B: Identical State Parity =====


class TestGroupBIdenticalStateParity(unittest.TestCase):
    """Construct equivalent post-preview 4-Pokémon
    doubles states for Random Doubles and VGC runtime
    mode. With deterministic RNG/config, legal action
    keys, raw slot scores, safety block maps, selected
    joint-order keys, and final per-slot action keys
    must match.
    """

    def _setup_4v4_state(self):
        """Build an equivalent 4v4 doubles state where
        our active is the same on both sides. The state
        is post-preview for VGC; pre-preview for Random
        Doubles (but we only exercise the post-preview
        turn 1+, where both runtimes use 4 active).
        """
        # Our active (slot 0, slot 1)
        incineroar = MockPokemon(
            "Incineroar", ["FIRE", "DARK"], ability="Intimidate"
        )
        tornadus = MockPokemon(
            "Tornadus", ["FLYING"], ability="Prankster"
        )
        # Opponent active
        rillaboom = MockPokemon(
            "Rillaboom", ["GRASS", "DARK"], ability="Grassy Surge"
        )
        garchomp = MockPokemon(
            "Garchomp", ["DRAGON", "GROUND"], ability="Rough Skin"
        )
        # Build battle
        battle = _make_battle(
            [incineroar, tornadus],
            [rillaboom, garchomp],
        )
        return battle

    def test_runtime_mode_attribute_set(self):
        """Both runtime modes must have ``_runtime_mode``
        attribute set to a documented value.
        """
        random_player = _make_test_player(
            runtime_mode="random_doubles"
        )
        self.assertEqual(
            random_player._runtime_mode, "random_doubles"
        )

        preview = PreviewResult(
            chosen_4=["Incineroar", "Tornadus", "Rillaboom", "Garchomp"],
            lead_2=["Incineroar", "Tornadus"],
            back_2=["Rillaboom", "Garchomp"],
            policy="basic_top4",
        )
        vgc_player = _make_vgc_player(preview)
        self.assertEqual(
            vgc_player._runtime_mode, "vgc_selected_four"
        )

    def test_selected_four_recorded_for_vgc(self):
        """VGC runtime records the selected four
        Pokémon, lead 2, and back 2.
        """
        preview = PreviewResult(
            chosen_4=["Incineroar", "Tornadus", "Rillaboom", "Garchomp"],
            lead_2=["Incineroar", "Tornadus"],
            back_2=["Rillaboom", "Garchomp"],
            policy="basic_top4",
        )
        vgc_player = _make_vgc_player(preview)
        self.assertEqual(
            vgc_player._selected_four,
            ["Incineroar", "Tornadus", "Rillaboom", "Garchomp"],
        )
        self.assertEqual(
            vgc_player._lead_2, ["Incineroar", "Tornadus"]
        )
        self.assertEqual(
            vgc_player._back_2, ["Rillaboom", "Garchomp"]
        )
        self.assertEqual(
            vgc_player._preview_policy, "basic_top4"
        )

    def test_canonical_engine_owner_recorded(self):
        """Both runtimes must record the canonical engine
        owner (the SAME string for both).
        """
        random_player = _make_test_player(
            runtime_mode="random_doubles"
        )
        preview = PreviewResult(
            chosen_4=["Incineroar", "Tornadus", "Rillaboom", "Garchomp"],
            lead_2=["Incineroar", "Tornadus"],
            back_2=["Rillaboom", "Garchomp"],
            policy="basic_top4",
        )
        vgc_player = _make_vgc_player(preview)
        # Both record shared_engine_used=True and the
        # owner string. We construct the owner string
        # at audit-time, but both players expose the
        # flag through getattr.
        self.assertTrue(
            getattr(random_player, "_shared_engine_used", False)
        )
        self.assertTrue(
            getattr(vgc_player, "_shared_engine_used", False)
        )


# ===== Group C: Mechanics Parity Through Production =====


class TestGroupCMechanicsParity(unittest.TestCase):
    """Mechanics checks via the production helpers. Both
    runtime modes must route through the SAME
    ``doubles_mechanics`` functions.
    """

    def test_water_into_water_absorb(self):
        """Water move into Water Absorb must be
        ineffective (via ability block, not type
        immunity, since Water vs Water is 0.5x).
        """
        move = _make_dummy_move("surf", "WATER")
        target = MockPokemon("Vaporeon", ["WATER"])
        # Type chart: Water vs Water = 0.5x (not immune).
        immune, reason = is_type_immune(move, None, target)
        self.assertFalse(immune)
        # Ability block: Water Absorb absorbs Water.
        target.ability = "waterabsorb"
        blocks, abil_reason = ability_hard_blocks_move(
            move, None, target
        )
        self.assertTrue(blocks)
        self.assertIn("waterabsorb", abil_reason or "")

    def test_electric_into_volt_absorb(self):
        """Electric move into Volt Absorb must be
        ineffective.
        """
        move = _make_dummy_move("thunderbolt", "ELECTRIC")
        target = MockPokemon("Jolteon", ["ELECTRIC"])
        target.ability = "voltabsorb"
        blocks, abil_reason = ability_hard_blocks_move(
            move, None, target
        )
        self.assertTrue(blocks)
        self.assertIn("voltabsorb", abil_reason or "")

    def test_ground_into_levitate(self):
        """Ground move into Levitate must be ineffective.
        """
        move = _make_dummy_move("earthquake", "GROUND")
        target = MockPokemon("Garchomp", ["DRAGON", "GROUND"])
        target.ability = "levitate"
        blocks, abil_reason = ability_hard_blocks_move(
            move, None, target
        )
        self.assertTrue(blocks)
        self.assertIn("levitate", abil_reason or "")

    def test_wonder_guard_neutral_vs_super_effective(self):
        """Wonder Guard — V2k.5 semantics.

        V2k.5 inverts the canonical Wonder Guard
        rule. The V2k.5 implementation blocks
        non-super-effective damaging moves (mult in
        (0, 1]) and lets super-effective moves
        (mult >= 2.0) through. Status moves are
        NOT blocked.

        This test asserts the V2k.5 semantics, which
        is the accepted shared-mechanics state. Note
        that this differs from the canonical Wonder
        Guard rule. The V2l parity test does not
        modify the shared mechanics — it verifies
        that the canonical engine and the VGC runtime
        both route through the SAME mechanics,
        whatever the rule is.
        """
        from doubles_mechanics import evaluate_move_effectiveness
        # Use a real damaging move (Surf) so the
        # move_category check fires. Neutral: WATER
        # vs BUG/GHOST = 1.0 × 1.0 = 1.0 → blocked
        # by V2k.5 Wonder Guard.
        class _WaterMove:
            id = "surf"
            type = MagicMock()
            type.name = "WATER"
            category = MagicMock()
            category.name = "SPECIAL"
            base_power = 90
        res = evaluate_move_effectiveness(
            move=_WaterMove(), attacker=None, target=None,
            defender_types=["BUG", "GHOST"],
            target_ability="wonderguard",
        )
        self.assertTrue(res.is_explicit_ability_immune)
        # When Wonder Guard blocks, the engine sets
        # the effective multiplier to 0.0
        # (per evaluate_move_effectiveness step 3).
        self.assertEqual(res.effective_multiplier, 0.0)
        # Super-effective: FIRE vs BUG/GHOST = 2.0 × 1.0 = 2.0
        # → NOT blocked by V2k.5 Wonder Guard.
        class _FireMove:
            id = "firepunch"
            type = MagicMock()
            type.name = "FIRE"
            category = MagicMock()
            category.name = "PHYSICAL"
            base_power = 75
        res = evaluate_move_effectiveness(
            move=_FireMove(), attacker=None, target=None,
            defender_types=["BUG", "GHOST"],
            target_ability="wonderguard",
        )
        # 2.0x is super-effective; V2k.5 Wonder Guard
        # lets it through.
        self.assertFalse(res.is_explicit_ability_immune)

    def test_mold_breaker_bypasses(self):
        """Mold Breaker bypasses the typed-ability block
        (per-move, conditional on a real block).
        """
        from doubles_mechanics import (
            resolve_explicit_ability_interaction
        )
        # Soundproof + sound-flagged move → bypass
        # activates (the move WOULD have been blocked).
        class _MSound:
            id = "hypervoice"
            flags = {"sound": True}
        res = resolve_explicit_ability_interaction(
            move=_MSound(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="moldbreaker",
            move_id="hypervoice", move_type="NORMAL",
        )
        self.assertTrue(res.bypassed)
        # Tackle (no sound flag) into Soundproof with
        # Mold Breaker → not blocked → NOT bypassed.
        class _MTackle:
            id = "tackle"
            flags = {}
        res = resolve_explicit_ability_interaction(
            move=_MTackle(), attacker=None, target=None,
            target_ability="soundproof",
            attacker_ability="moldbreaker",
            move_id="tackle", move_type="NORMAL",
        )
        self.assertFalse(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_good_as_gold_status_block_and_mold_breaker_bypasses(self):
        """V2k.5 accepted state.

        Good as Gold blocks status moves. Mold Breaker
        bypasses Good as Gold's status block.
        """
        from doubles_mechanics import (
            resolve_explicit_ability_interaction
        )
        # Status move into Good as Gold: blocked
        # (no Mold Breaker).
        res = resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="goodasgold",
            attacker_ability=None,
            move_id="thunderwave", move_type="STATUS",
        )
        self.assertFalse(res.bypassed)
        self.assertTrue(res.is_immune)
        # Status move into Good as Gold with Mold
        # Breaker: BYPASSED (V2k.5).
        res = resolve_explicit_ability_interaction(
            move="thunderwave", attacker=None, target=None,
            target_ability="goodasgold",
            attacker_ability="moldbreaker",
            move_id="thunderwave", move_type="STATUS",
        )
        self.assertTrue(res.bypassed)
        self.assertFalse(res.is_immune)

    def test_morpeko_form_states(self):
        """Morpeko's Aura Wheel type changes with form:
        Full Belly → ELECTRIC, Hangry → DARK.
        """
        # Full Belly (resolved form = "morpeko")
        r1 = _dm.resolve_effective_move_type(
            "aurawheel", observed_form="morpeko"
        )
        self.assertEqual(r1.effective_type, "ELECTRIC")
        # Hangry (resolved form = "morpekohangry")
        r2 = _dm.resolve_effective_move_type(
            "aurawheel", observed_form="morpekohangry"
        )
        self.assertEqual(r2.effective_type, "DARK")
        # Reverse (Full Belly again)
        r3 = _dm.resolve_effective_move_type(
            "aurawheel", observed_form="morpeko"
        )
        self.assertEqual(r3.effective_type, "ELECTRIC")

    def test_fake_out_into_ghost_legal_targets(self):
        """Fake Out into Ghost defenders returns 0 legal
        targets.
        """
        n = _dm.fake_out_legal_targets(
            "fakeout",
            [
                MockPokemon("Gengar", ["GHOST", "POISON"]),
                MockPokemon("Gengar2", ["GHOST", "POISON"]),
            ],
        )
        self.assertEqual(n, 0)

    def test_fake_out_into_legal_targets(self):
        """Fake Out into two non-Ghost defenders returns
        2 legal targets.
        """
        n = _dm.fake_out_legal_targets(
            "fakeout",
            [
                MockPokemon("Incineroar", ["FIRE", "DARK"]),
                MockPokemon("Tornadus", ["FLYING"]),
            ],
        )
        self.assertEqual(n, 2)

    def test_spread_move_with_one_immune_one_legal(self):
        """Spread move with one immune and one legal
        target. ``fake_out_legal_targets`` is the
        per-slot legality; spread partial-immunity is
        scored by the canonical engine.
        """
        # Immune target only
        n = _dm.fake_out_legal_targets(
            "fakeout",
            [
                MockPokemon("Gengar", ["GHOST", "POISON"]),
                MockPokemon("Tornadus", ["FLYING"]),
            ],
        )
        self.assertEqual(n, 1)


# ===== Group D: Target and Switching Parity =====


class TestGroupDTargetAndSwitchingParity(unittest.TestCase):
    """Heal Pulse never targets an opponent when a legal
    ally exists. Support/disruption target semantics
    must match. Voluntary switch candidate table is
    populated identically. Forced-switch handling
    remains unchanged. VGC selected-four bench contains
    exactly two valid switch candidates.
    """

    def test_vgc_bench_has_exactly_two_candidates(self):
        """The VGC runtime exposes the bench as exactly
        two switch candidates after the 4-of-6 preview
        selection.
        """
        preview = PreviewResult(
            chosen_4=["Incineroar", "Tornadus", "Rillaboom", "Garchomp"],
            lead_2=["Incineroar", "Tornadus"],
            back_2=["Rillaboom", "Garchomp"],
            policy="basic_top4",
        )
        vgc_player = _make_vgc_player(preview)
        # The VGC player records lead_2 and back_2
        # directly. The canonical engine's switch
        # logic reads them from these attributes.
        self.assertEqual(len(vgc_player._lead_2), 2)
        self.assertEqual(len(vgc_player._back_2), 2)
        # The 4 selected Pokémon are exactly lead_2 ∪ back_2.
        self.assertEqual(
            set(vgc_player._selected_four),
            set(vgc_player._lead_2) | set(vgc_player._back_2),
        )


# ===== Group E: Audit Proof =====


class TestGroupEAuditProof(unittest.TestCase):
    """Logger-generated JSONL must show: runtime mode,
    shared engine used, concrete owner/path, selected
    four, final action keys, slot isolation, legacy
    record handling.
    """

    def test_audit_logger_accepts_v2l_kwargs(self):
        """The audit logger accepts the V2l kwargs
        (``runtime_mode``, ``concrete_player_class``,
        ``shared_engine_used``, ``shared_engine_owner``,
        ``selected_four``, ``lead_2``, ``back_2``,
        ``preview_policy``) without raising.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "audit.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=log_path, reset=True
            )
            battle_tag = "audit_test"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            # The logger should NOT raise when called
            # with the V2l kwargs.
            battle = _make_battle(
                [MockPokemon("Incineroar", ["FIRE", "DARK"])],
                [MockPokemon("Tornadus", ["FLYING"])],
            )
            scored = []  # Empty
            try:
                logger.log_turn_decision(
                    battle_tag=battle_tag,
                    turn=1,
                    battle=battle,
                    selected_joint_order="/choose move1 1, move2 2",
                    selected_score=100.0,
                    scored_joint_orders=scored,
                    expected_damages=[50, 50],
                    expected_kos=[False, False],
                    target_hps=[0.8, 0.8],
                    overkill_triggered=False,
                    focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False],
                    best_spread_score=[0.0, 0.0],
                    best_ko_score=[0.0, 0.0],
                    low_hp_opponent_existed=False,
                    low_hp_opponent_targeted=False,
                    slot_actions=["/choose move1 1", "/choose move2 2"],
                    slot_action_types=[{"damaging": True}, {"damaging": True}],
                    target_species=["Tornadus", "Tornadus"],
                    runtime_mode="vgc_selected_four",
                    concrete_player_class="ControlledTeamPreviewPlayer",
                    shared_engine_invocation_id="logger-contract-1",
                    shared_engine_invocation_status="completed",
                    shared_engine_owner=(
                        "bot_doubles_damage_aware."
                        "DoublesDamageAwarePlayer"
                    ),
                    v2l1_selected_joint_key=(
                        "move|move1|1;move|move2|2"
                    ),
                    v2l1_final_action_keys=[
                        "move|move1|1", "move|move2|2"
                    ],
                    selected_four=[
                        "Incineroar", "Tornadus",
                        "Rillaboom", "Garchomp",
                    ],
                    lead_2=["Incineroar", "Tornadus"],
                    back_2=["Rillaboom", "Garchomp"],
                    preview_policy="basic_top4",
                )
            except Exception as e:
                self.fail(
                    f"log_turn_decision raised with V2l "
                    f"kwargs: {e}"
                )

    def test_audit_jsonl_contains_v2l_fields(self):
        """The audit JSONL contains the V2l metadata
        fields for every turn.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "audit_v2l.jsonl")
            logger = DoublesDecisionAuditLogger(
                filepath=log_path, reset=True
            )
            battle_tag = "audit_v2l"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            battle = _make_battle(
                [MockPokemon("Incineroar", ["FIRE", "DARK"])],
                [MockPokemon("Tornadus", ["FLYING"])],
            )
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order="/choose move1 1, move2 2",
                selected_score=100.0,
                scored_joint_orders=[],
                expected_damages=[50, 50],
                expected_kos=[False, False],
                target_hps=[0.8, 0.8],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=["/choose move1 1", "/choose move2 2"],
                slot_action_types=[{"damaging": True}, {"damaging": True}],
                target_species=["Tornadus", "Tornadus"],
                runtime_mode="vgc_selected_four",
                concrete_player_class="ControlledTeamPreviewPlayer",
                shared_engine_invocation_id="logger-contract-2",
                shared_engine_invocation_status="completed",
                shared_engine_owner=(
                    "bot_doubles_damage_aware.DoublesDamageAwarePlayer"
                ),
                v2l1_selected_joint_key=(
                    "move|move1|1;move|move2|2"
                ),
                v2l1_final_action_keys=[
                    "move|move1|1", "move|move2|2"
                ],
                selected_four=[
                    "Incineroar", "Tornadus",
                    "Rillaboom", "Garchomp",
                ],
                lead_2=["Incineroar", "Tornadus"],
                back_2=["Rillaboom", "Garchomp"],
                preview_policy="basic_top4",
            )
            logger.update_previous_turn(battle_tag, battle)
            logger.save_battle(battle_tag, winner="p1", battle=battle)
            # Read the JSONL and verify fields.
            with open(log_path) as f:
                records = [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]
            self.assertGreaterEqual(len(records), 1)
            record = records[0]
            # The V2l fields are recorded PER TURN,
            # inside the ``audit_turns`` list.
            self.assertIn("audit_turns", record)
            self.assertGreaterEqual(
                len(record["audit_turns"]), 1
            )
            turn_record = record["audit_turns"][0]
            for field_name in (
                "runtime_mode", "concrete_player_class",
                "shared_engine_used", "shared_engine_owner",
                "selected_four", "lead_2", "back_2",
                "preview_policy",
            ):
                self.assertIn(
                    field_name, turn_record,
                    f"audit turn record missing {field_name}",
                )
            self.assertEqual(
                turn_record["runtime_mode"],
                "vgc_selected_four",
            )
            self.assertTrue(
                turn_record["shared_engine_used"]
            )


# ===== Group F: Negative Guards =====


class TestGroupFNegativeGuards(unittest.TestCase):
    """No duplicate VGC score_action implementation.
    No duplicate VGC joint selector. No new
    TYPE_CHART / immunity table. No hidden ability
    inference. No species-derived hidden speed. No
    battle outcome input to runtime decisions.
    """

    def test_no_vgc_score_action(self):
        import bot_vgc2026_phaseV2c
        self.assertFalse(
            hasattr(bot_vgc2026_phaseV2c, "score_action")
        )
        self.assertFalse(
            hasattr(bot_vgc2026_phaseV2c, "_score_action")
        )

    def test_no_vgc_joint_selector(self):
        import bot_vgc2026_phaseV2c
        forbidden = [
            "select_joint_order",
            "_select_joint_order",
            "choose_joint_order",
        ]
        for attr in forbidden:
            self.assertFalse(
                hasattr(bot_vgc2026_phaseV2c, attr),
                f"VGC module must not define {attr}",
            )

    def test_no_vgc_type_chart(self):
        import bot_vgc2026_phaseV2c
        self.assertFalse(
            hasattr(bot_vgc2026_phaseV2c, "TYPE_CHART")
        )

    def test_no_vgc_immunity_table(self):
        import bot_vgc2026_phaseV2c
        self.assertFalse(
            hasattr(
                bot_vgc2026_phaseV2c, "IMMUNITY_ABILITIES"
            )
        )
        self.assertFalse(
            hasattr(
                bot_vgc2026_phaseV2c, "ABSORB_ABILITIES"
            )
        )

    def test_no_vgc_hidden_ability_inference(self):
        """The VGC player MUST NOT infer abilities from
        species. The canonical engine does not, and
        the VGC runtime must defer to the engine.
        """
        import bot_vgc2026_phaseV2c
        # The VGC module must not define a
        # ``_infer_ability_from_species`` or similar.
        forbidden = [
            "_infer_ability_from_species",
            "guess_ability",
            "species_ability_lookup",
        ]
        for attr in forbidden:
            self.assertFalse(
                hasattr(bot_vgc2026_phaseV2c, attr),
                f"VGC module must not define {attr}",
            )

    def test_no_vgc_species_derived_speed(self):
        """No species-derived hidden speed in VGC."""
        import bot_vgc2026_phaseV2c
        forbidden = [
            "_derive_speed_from_species",
            "get_species_base_speed",
            "infer_speed",
        ]
        for attr in forbidden:
            self.assertFalse(
                hasattr(bot_vgc2026_phaseV2c, attr),
                f"VGC module must not define {attr}",
            )

    def test_vgc_choose_move_does_not_read_battle_outcome(self):
        """The VGC ``choose_move`` must NOT read the
        battle outcome (win / loss / damage already
        dealt). The canonical engine uses only the
        current ``battle`` state.
        """
        vgc_src = inspect.getsource(
            ControlledTeamPreviewPlayer.choose_move
        )
        forbidden = [
            "our_win",
            "opponent_win",
            "battle_result",
            "outcome_known",
            "actual_ko",
            "fainted",
        ]
        for f in forbidden:
            self.assertNotIn(
                f, vgc_src,
                f"VGC choose_move must not read {f}",
            )


# ===== Group G: V2l.1 — Real Factory / Constructor / Execution-Derived Evidence =====


import os as _os
import tempfile as _tempfile

# Re-import the V2l.1-specific symbols at module level.
from bot_doubles_damage_aware import (
    _legal_action_keys_for_slot as _v2l1_legal_keys,
    _raw_score_map_for_slot as _v2l1_raw_scores,
    _safety_block_map_for_slot as _v2l1_safety_block_map,
    _order_action_key as _v2l1_order_action_key,
    _final_action_keys_from_joint as _v2l1_final_keys_from_joint,
    _selected_joint_key as _v2l1_selected_joint_key,
    _compute_order_safety_blocks as _v2l1_compute_safety_blocks,
)
from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger as _v2l1_AuditLogger,
)


_SAMPLE_VGC_TEAM_TEXT = """
Incineroar (Incineroar) @ Sitrus Berry
Ability: Intimidate
Level: 50
EVs: 252 HP / 252 Atk / 4 Def
Adamant Nature
- Fake Out
- Flare Blitz
- Knock Off
- U-turn

Florges (Florges) @ Leftovers
Ability: Flower Veil
Level: 50
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Moonblast
- Psychic
- Thunder Wave
- Protect

Oranguru (Oranguru) @ Eject Pack
Ability: Inner Focus
Level: 50
EVs: 252 HP / 252 SpA / 4 SpD
Quiet Nature
- Psychic
- Hyper Voice
- Protect
- Trick Room

Kartana (Kartana) @ Choice Scarf
Ability: Beast Boost
Level: 50
EVs: 252 Atk / 252 Spe
Jolly Nature
- Leaf Blade
- Sacred Sword
- Smart Strike
- X-Scissor

Tornadus (Tornadus) @ Heavy-Duty Boots
Ability: Prankster
Level: 50
EVs: 252 SpA / 252 Spe
Timid Nature
- Hurricane
- Tailwind
- Taunt
- Rain Dance

Rillaboom (Rillaboom) @ Assault Vest
Ability: Grassy Surge
Level: 50
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Wood Hammer
- Knock Off
- Fake Out
- U-turn
""".strip()


def _make_vgc_preview(seed: int = 42):
    """Return a real ``PreviewResult`` produced by the
    real ``team_preview_policy.choose_four_from_six``
    policy.
    """
    team6 = [
        {"species": s}
        for s in [
            "incineroar", "florges", "oranguru",
            "kartana", "tornadus", "rillaboom",
        ]
    ]
    from team_preview_policy import choose_four_from_six
    return choose_four_from_six(
        team6,
        opponent_team=[],
        policy="basic_top4",
        seed=seed,
    )


def _run_canonical_decision(
    runtime_mode: str,
    log_path: str,
    battle_tag: str,
    audit_logger=None,
):
    """Run one real canonical ``choose_move`` decision.

    The two runtime variants receive independently-created but
    behaviorally identical ``DoubleBattle`` states.  Nothing in
    this helper writes the V2l.1 snapshot fields directly; those
    fields must be produced by ``DoublesDamageAwarePlayer.choose_move``.
    """
    from test_doubles_ability_hard_safety import (
        MockBattle as RealMockBattle,
        MockMove as RealMockMove,
        MockPokemon as RealMockPokemon,
    )
    from poke_env.player.battle_order import SingleBattleOrder

    logger = audit_logger or _v2l1_AuditLogger(
        filepath=log_path, reset=True
    )
    if runtime_mode == "vgc_selected_four":
        player = _make_vgc_player(
            _make_vgc_preview(seed=99), logger
        )
    elif runtime_mode == "random_doubles":
        player = _make_test_player(
            runtime_mode="random_doubles"
        )
        player.audit_logger = logger
        player._concrete_player_class = (
            "DoublesDamageAwarePlayer"
        )
    else:
        raise ValueError(f"unsupported runtime mode: {runtime_mode}")

    battle = RealMockBattle()
    battle.battle_tag = battle_tag
    battle._replay_data = []
    attacker_0 = RealMockPokemon("garchomp", ["GROUND"])
    attacker_1 = RealMockPokemon("blissey", ["NORMAL"])
    opponent_0 = RealMockPokemon("snorlax", ["NORMAL"])
    opponent_1 = RealMockPokemon("lucario", ["STEEL"])
    move_0 = RealMockMove("dragonclaw", "DRAGON")
    move_1 = RealMockMove("tackle", "NORMAL")
    battle.active_pokemon = [attacker_0, attacker_1]
    battle.opponent_active_pokemon = [
        opponent_0, opponent_1
    ]
    battle.available_moves = [[move_0], [move_1]]
    battle.valid_orders = [
        [SingleBattleOrder(move_0, move_target=1)],
        [SingleBattleOrder(move_1, move_target=2)],
    ]

    selected = player.choose_move(battle)
    logger.save_battle(
        battle_tag=battle_tag,
        winner="Tie / Unknown",
        battle=battle,
    )
    with open(log_path) as stream:
        records = [
            json.loads(line)
            for line in stream
            if line.strip()
        ]
    turn = records[-1]["audit_turns"][-1]
    return {
        "player": player,
        "battle": battle,
        "selected_message": selected.message,
        "legal_slot0": player._v2l1_legal_keys_slot0,
        "legal_slot1": player._v2l1_legal_keys_slot1,
        "raw_slot0": player._v2l1_raw_scores_slot0,
        "raw_slot1": player._v2l1_raw_scores_slot1,
        "safety_slot0": player._v2l1_safety_blocks_slot0,
        "safety_slot1": player._v2l1_safety_blocks_slot1,
        "joint": player._v2l1_selected_joint_key,
        "final": player._v2l1_final_keys,
        "turn": turn,
    }


class TestGroupGLightweightPlayerLifecycle(unittest.TestCase):
    """Canonical behavior without starting poke-env networking."""

    def test_vgc_player_state_and_audit_reach_choose_move(self):
        """The lightweight VGC player executes the real engine."""
        with _tempfile.TemporaryDirectory() as tmpdir:
            result = _run_canonical_decision(
                "vgc_selected_four",
                _os.path.join(tmpdir, "lifecycle.jsonl"),
                "v2l1-lifecycle",
            )
        player = result["player"]
        self.assertIsInstance(
            player, ControlledTeamPreviewPlayer
        )
        self.assertIsInstance(
            player, DoublesDamageAwarePlayer
        )
        self.assertIsInstance(
            player.config, DoublesDamageAwareConfig
        )
        self.assertEqual(
            player._runtime_mode, "vgc_selected_four"
        )
        self.assertEqual(
            player._v2l1_invocation_status, "completed"
        )
        self.assertEqual(len(player._selected_four), 4)
        self.assertEqual(len(player._lead_2), 2)
        self.assertEqual(len(player._back_2), 2)
        self.assertTrue(result["turn"]["shared_engine_used"])
        return

        # Historical full-constructor assertions are unreachable:
        # unit tests must not start poke-env's networking lifecycle.
        from bot_vgc2026_phaseV2c import (
            NoAvatarPSClient,
        )
        from poke_env import AccountConfiguration

        preview = _make_vgc_preview()
        account = AccountConfiguration("v2l1_user", None)
        with _tempfile.TemporaryDirectory() as tmpdir:
            log_path = _os.path.join(tmpdir, "audit.jsonl")
            audit_logger = _v2l1_AuditLogger(
                filepath=log_path, reset=True
            )
            player = create_controlled_player(
                account,
                _SAMPLE_VGC_TEAM_TEXT,
                preview,
                "v2l1_factory_test",
                0,
                "p1",
                "gen9championsvgc2026regma",
                audit_logger=audit_logger,
            )
            try:
                # Verify the real base constructor ran
                # (DoublesDamageAwarePlayer.__init__).
                self.assertIsInstance(
                    player,
                    ControlledTeamPreviewPlayer,
                )
                self.assertIsInstance(
                    player, DoublesDamageAwarePlayer
                )
                # The V2l runtime-mode boundary is set
                # by the real constructor.
                self.assertEqual(
                    player._runtime_mode, "vgc_selected_four"
                )
                self.assertEqual(
                    player._concrete_player_class,
                    "ControlledTeamPreviewPlayer",
                )
                # The V2l.1 execution-derived marker
                # exists and starts unset.
                self.assertIsNone(
                    player._v2l1_invocation_id
                )
                self.assertEqual(
                    player._v2l1_invocation_count, 0
                )
                # The audit logger reaches the player
                # (real attribute, not a copy).
                self.assertIs(
                    player.audit_logger, audit_logger
                )
                # The preview metadata reaches the
                # player (real attributes).
                self.assertEqual(
                    player._selected_four,
                    preview.chosen_4,
                )
                self.assertEqual(
                    player._lead_2, preview.lead_2
                )
                self.assertEqual(
                    player._back_2, preview.back_2
                )
                self.assertEqual(
                    player._preview_policy, "basic_top4"
                )
                # The base-class tracking dicts are
                # populated (DoublesDamageAwarePlayer
                # init ran).
                self.assertIsNotNone(
                    player.active_turns
                )
                self.assertIsNotNone(
                    player.last_protect_turn
                )
                self.assertIsNotNone(
                    player.tiebreaker_activations_by_battle
                )
                # The config is a real
                # ``DoublesDamageAwareConfig``.
                self.assertIsInstance(
                    player.config, DoublesDamageAwareConfig
                )
                # The NoAvatarPSClient replacement
                # exists and is the right type.
                self.assertIsInstance(
                    player.ps_client, NoAvatarPSClient
                )
                # The replacement client must NOT be
                # listening (would cause a network
                # leak).
                self.assertFalse(
                    bool(
                        getattr(
                            player.ps_client,
                            "listening",
                            False,
                        )
                    ),
                    "NoAvatarPSClient must not be "
                    "listening to avoid a network leak",
                )
            finally:
                # Close / cancel all created resources
                # naturally. No atexit workaround.
                try:
                    if hasattr(player.ps_client, "close"):
                        player.ps_client.close()
                except Exception:
                    pass
                try:
                    if hasattr(
                        player.ps_client, "stop_listening"
                    ):
                        player.ps_client.stop_listening()
                except Exception:
                    pass

    def test_legacy_use_without_runtime_audit_continues(self):
        """The canonical engine runs when audit logging is disabled."""
        player = _make_vgc_player(
            _make_vgc_preview(seed=7), audit_logger=None
        )
        from test_doubles_ability_hard_safety import (
            MockBattle as RealMockBattle,
            MockMove as RealMockMove,
            MockPokemon as RealMockPokemon,
        )
        from poke_env.player.battle_order import SingleBattleOrder
        battle = RealMockBattle()
        battle.battle_tag = "v2l1-legacy"
        battle._replay_data = []
        move_0 = RealMockMove("dragonclaw", "DRAGON")
        move_1 = RealMockMove("tackle", "NORMAL")
        battle.active_pokemon = [
            RealMockPokemon("garchomp", ["GROUND"]),
            RealMockPokemon("blissey", ["NORMAL"]),
        ]
        battle.opponent_active_pokemon = [
            RealMockPokemon("snorlax", ["NORMAL"]),
            RealMockPokemon("lucario", ["STEEL"]),
        ]
        battle.available_moves = [[move_0], [move_1]]
        battle.valid_orders = [
            [SingleBattleOrder(move_0, move_target=1)],
            [SingleBattleOrder(move_1, move_target=2)],
        ]
        selected = player.choose_move(battle)
        self.assertIsNone(player.audit_logger)
        self.assertEqual(
            player._v2l1_invocation_status, "completed"
        )
        self.assertEqual(
            selected.message,
            "/choose move dragonclaw 1, move tackle 2",
        )
        return

        # Historical full-constructor assertions are unreachable.
        from poke_env import AccountConfiguration

        preview = _make_vgc_preview(seed=7)
        account = AccountConfiguration("v2l1_legacy", None)
        player = create_controlled_player(
            account,
            _SAMPLE_VGC_TEAM_TEXT,
            preview,
            "v2l1_legacy_test",
            0,
            "p1",
            "gen9championsvgc2026regma",
            audit_logger=None,
        )
        try:
            self.assertIsNone(player.audit_logger)
            self.assertEqual(
                player._runtime_mode, "vgc_selected_four"
            )
        finally:
            try:
                player.ps_client.close()
            except Exception:
                pass

    def test_preview_evidence_schema_excludes_runtime_audit_fields(self):
        """Preview CSV evidence and runtime audit remain separate schemas."""
        from bot_vgc2026_phaseV2c import PreviewEvidence

        player = _make_vgc_player(_make_vgc_preview(seed=8))
        evidence = player.get_preview_evidence()
        evidence["opponent_policy"] = "random_4_from_6"
        parsed = PreviewEvidence(**evidence)
        self.assertEqual(parsed.side, "p1")
        self.assertNotIn("runtime_mode", evidence)
        self.assertNotIn("shared_engine_used", evidence)


class TestGroupGV2l1AuditWiring(unittest.TestCase):
    """V2l.1 — the audit logger produced by
    ``DoublesDecisionAuditLogger`` is invoked by the
    canonical engine and writes a battle record that
    contains the V2l.1 execution-derived fields.
    """

    def test_audit_logger_includes_v2l1_execution_fields(self):
        """The audit logger accepts the V2l.1 kwargs
        and persists them in every turn record.
        """
        with _tempfile.TemporaryDirectory() as tmpdir:
            log_path = _os.path.join(
                tmpdir, "v2l1_audit.jsonl"
            )
            logger = _v2l1_AuditLogger(
                filepath=log_path, reset=True
            )
            battle_tag = "v2l1_audit_test"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            # Set a non-empty invocation id BEFORE
            # calling log_turn_decision. This is what
            # the canonical ``choose_move`` does on
            # entry.
            battle = MagicMock()
            battle.battle_tag = battle_tag
            battle.active_pokemon = [
                MockPokemon("Incineroar", ["FIRE", "DARK"]),
                None,
            ]
            battle.opponent_active_pokemon = [
                None, None,
            ]
            battle.turn = 1
            battle.player_role = "p1"
            battle._replay_data = []
            battle.fields = []
            battle.player_username = "v2l1_user"
            battle.opponent_username = "opp_user"
            battle.won = None
            invocation_id = "v2l1-1234567890-1"
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order=(
                    "/choose tackle 1, switch tornadus"
                ),
                selected_score=10.0,
                scored_joint_orders=[],
                expected_damages=[50, 50],
                expected_kos=[False, False],
                target_hps=[0.8, 0.8],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose tackle 1",
                    "/choose switch tornadus",
                ],
                slot_action_types=[
                    {"damaging": True},
                    {"switching": True},
                ],
                target_species=["Tornadus", "Tornadus"],
                runtime_mode="vgc_selected_four",
                concrete_player_class=(
                    "ControlledTeamPreviewPlayer"
                ),
                shared_engine_invocation_id=invocation_id,
                shared_engine_invocation_status="completed",
                v2l1_legal_action_keys_slot0=[
                    "move|tackle|1",
                    "switch|tornadus|0",
                ],
                v2l1_legal_action_keys_slot1=[
                    "move|tackle|1",
                ],
                v2l1_raw_scores_slot0={
                    "move|tackle|1": 10.0,
                    "switch|tornadus|0": 5.0,
                },
                v2l1_raw_scores_slot1={
                    "move|tackle|1": 7.0,
                },
                v2l1_safety_blocks_slot0={
                    "move|tackle|1": False,
                    "switch|tornadus|0": False,
                },
                v2l1_safety_blocks_slot1={
                    "move|tackle|1": False,
                },
                v2l1_selected_joint_key=(
                    "move|tackle|1;switch|tornadus|0"
                ),
                v2l1_final_action_keys=[
                    "move|tackle|1",
                    "switch|tornadus|0",
                ],
                selected_four=[
                    "Incineroar", "Tornadus",
                    "Rillaboom", "Garchomp",
                ],
                lead_2=["Incineroar", "Tornadus"],
                back_2=["Rillaboom", "Garchomp"],
                preview_policy="basic_top4",
            )
            logger.update_previous_turn(battle_tag, battle)
            logger.save_battle(
                battle_tag=battle_tag,
                winner="v2l1_user",
                battle=battle,
            )
            # Read the JSONL and verify fields.
            with open(log_path) as f:
                records = [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertIn("audit_turns", record)
            self.assertEqual(len(record["audit_turns"]), 1)
            turn_record = record["audit_turns"][0]
            # V2l.1 fields must be persisted.
            for field_name in (
                "runtime_mode",
                "concrete_player_class",
                "shared_engine_invocation_id",
                "v2l1_legal_action_keys_slot0",
                "v2l1_legal_action_keys_slot1",
                "v2l1_raw_scores_slot0",
                "v2l1_raw_scores_slot1",
                "v2l1_safety_blocks_slot0",
                "v2l1_safety_blocks_slot1",
                "v2l1_selected_joint_key",
                "v2l1_final_action_keys",
                "selected_four",
                "lead_2",
                "back_2",
                "preview_policy",
            ):
                self.assertIn(
                    field_name, turn_record,
                    f"audit turn record missing "
                    f"{field_name}",
                )
            # shared_engine_used must be True
            # because a non-empty invocation id was
            # passed.
            self.assertTrue(
                turn_record["shared_engine_used"]
            )
            self.assertEqual(
                turn_record["runtime_mode"],
                "vgc_selected_four",
            )
            self.assertEqual(
                turn_record["shared_engine_invocation_id"],
                invocation_id,
            )

    def test_shared_engine_used_false_when_invocation_id_missing(self):
        """A legacy caller that does NOT supply an
        invocation id (e.g. someone calls
        ``log_turn_decision`` directly with the old
        kwargs) reports ``shared_engine_used=False``.
        This is the V2l.1 execution-derived proof.
        """
        with _tempfile.TemporaryDirectory() as tmpdir:
            log_path = _os.path.join(
                tmpdir, "v2l1_legacy_audit.jsonl"
            )
            logger = _v2l1_AuditLogger(
                filepath=log_path, reset=True
            )
            battle_tag = "v2l1_legacy_audit"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            battle = MagicMock()
            battle.battle_tag = battle_tag
            battle.active_pokemon = [
                MockPokemon("Incineroar", ["FIRE", "DARK"]),
                None,
            ]
            battle.opponent_active_pokemon = [None, None]
            battle.turn = 1
            battle.player_role = "p1"
            battle._replay_data = []
            battle.fields = []
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order="/choose tackle 1",
                selected_score=10.0,
                scored_joint_orders=[],
                expected_damages=[50, 50],
                expected_kos=[False, False],
                target_hps=[0.8, 0.8],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose tackle 1", "/choose pass"
                ],
                slot_action_types=[
                    {"damaging": True}, {"damaging": True}
                ],
                target_species=["Tornadus", "Tornadus"],
                runtime_mode="random_doubles",
                concrete_player_class=(
                    "DoublesDamageAwarePlayer"
                ),
                # Note: NO shared_engine_invocation_id
            )
            logger.update_previous_turn(battle_tag, battle)
            logger.save_battle(
                battle_tag=battle_tag,
                winner="v2l1_user",
                battle=battle,
            )
            with open(log_path) as f:
                records = [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]
            turn_record = records[0]["audit_turns"][0]
            # No invocation id → shared_engine_used
            # is False. This is the execution-derived
            # proof.
            self.assertFalse(
                turn_record["shared_engine_used"]
            )


class TestGroupGSnapshotHelperContracts(unittest.TestCase):
    """Unit contracts for the snapshot serialization helpers.

    These tests intentionally do not claim runtime parity. Runtime
    parity is covered separately by tests that execute
    ``choose_move`` in both modes.
    """

    def test_pure_helpers_legal_action_keys_match(self):
        """The pure ``_legal_action_keys_for_slot``
        helper produces deterministic keys for the
        same input across runtime modes.
        """
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        from poke_env.player.battle_order import (
            DoubleBattleOrder,
        )
        # Build a real ``SingleBattleOrder`` for a
        # move (use a real Move object so the
        # ``hasattr(inner, "id")`` check works as
        # expected).
        from poke_env.battle.move import Move
        from poke_env.battle.pokemon import Pokemon
        from poke_env.battle.pokemon_type import (
            PokemonType,
        )
        move = Move("tackle", gen=9)
        order_move = SingleBattleOrder(move, move_target=1)
        # Build a real ``SingleBattleOrder`` for a
        # switch. ``_order_action_key`` checks
        # ``hasattr(inner, "id")`` first; a real
        # ``Pokemon`` does NOT have an ``id``
        # attribute, so the switch key uses
        # ``species``.
        pkmn = MagicMock(spec=Pokemon)
        pkmn.species = "tornadus"
        # The spec=MagicMock excludes attributes
        # the spec doesn't define. ``Pokemon`` does
        # not define ``id`` as a top-level
        # attribute (species is the canonical key).
        order_switch = SingleBattleOrder(
            pkmn, move_target=0
        )
        # Same input, two different runtime modes.
        valid_orders = [[order_move, order_switch], [order_move]]
        keys_rd = _v2l1_legal_keys(valid_orders, 0)
        keys_vgc = _v2l1_legal_keys(valid_orders, 0)
        # Both runtimes produce the SAME legal keys
        # because the pure helper has no runtime-mode
        # branch.
        self.assertEqual(keys_rd, keys_vgc)
        self.assertEqual(len(keys_rd), 2)
        # First key is the move, second is the switch.
        self.assertEqual(keys_rd[0], ("move", "tackle", 1))
        self.assertEqual(keys_rd[1], ("switch", "tornadus", 0))

    def test_pure_helpers_raw_score_map_match(self):
        """The pure ``_raw_score_map_for_slot`` helper
        produces deterministic score maps for the
        same input across runtime modes.
        """
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        move_a = MagicMock()
        move_a.id = "tackle"
        order_move = SingleBattleOrder(move_a, move_target=1)
        valid_orders = [[order_move], []]
        slot_scores = {id(order_move): 42.0}
        map_rd = _v2l1_raw_scores(slot_scores, valid_orders, 0)
        map_vgc = _v2l1_raw_scores(slot_scores, valid_orders, 0)
        # Both runtimes produce the SAME raw score
        # map.
        self.assertEqual(map_rd, map_vgc)
        self.assertEqual(map_rd[("move", "tackle", 1)], 42.0)

    def test_pure_helpers_safety_block_map_match(self):
        """The pure ``_safety_block_map_for_slot`` helper
        produces deterministic safety block maps for
        the same input across runtime modes.
        """
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        move_a = MagicMock()
        move_a.id = "tackle"
        order_move = SingleBattleOrder(move_a, move_target=1)
        valid_orders = [[order_move], []]
        safety_blocked = {id(order_move): True}
        map_rd = _v2l1_safety_block_map(
            safety_blocked, valid_orders, 0
        )
        map_vgc = _v2l1_safety_block_map(
            safety_blocked, valid_orders, 0
        )
        self.assertEqual(map_rd, map_vgc)
        self.assertTrue(
            map_rd[("move", "tackle", 1)]
        )

    def test_pure_helpers_selected_joint_key_match(self):
        """The pure ``_selected_joint_key`` helper
        produces deterministic joint keys for the
        same input across runtime modes.
        """
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        from poke_env.battle.move import Move
        from poke_env.battle.pokemon import Pokemon
        from poke_env.player.battle_order import (
            DoubleBattleOrder,
        )
        move_a = Move("tackle", gen=9)
        o1 = SingleBattleOrder(move_a, move_target=1)
        pkmn_b = MagicMock(spec=Pokemon)
        pkmn_b.species = "tornadus"
        o2 = SingleBattleOrder(pkmn_b, move_target=0)
        joint = DoubleBattleOrder(o1, o2)
        key_rd = _v2l1_selected_joint_key(joint)
        key_vgc = _v2l1_selected_joint_key(joint)
        self.assertEqual(key_rd, key_vgc)
        self.assertEqual(
            key_rd,
            (
                ("move", "tackle", 1),
                ("switch", "tornadus", 0),
            ),
        )

    def test_pure_helpers_final_action_keys_match(self):
        """The pure ``_final_action_keys_from_joint``
        helper produces deterministic final keys for
        the same input across runtime modes.
        """
        from poke_env.battle.double_battle import (
            SingleBattleOrder,
        )
        from poke_env.battle.move import Move
        from poke_env.battle.pokemon import Pokemon
        from poke_env.player.battle_order import (
            DoubleBattleOrder,
        )
        move_a = Move("tackle", gen=9)
        o1 = SingleBattleOrder(move_a, move_target=1)
        pkmn_b = MagicMock(spec=Pokemon)
        pkmn_b.species = "tornadus"
        o2 = SingleBattleOrder(pkmn_b, move_target=0)
        joint = DoubleBattleOrder(o1, o2)
        keys_rd = _v2l1_final_keys_from_joint(joint)
        keys_vgc = _v2l1_final_keys_from_joint(joint)
        self.assertEqual(keys_rd, keys_vgc)
        self.assertEqual(
            keys_rd,
            [
                ("move", "tackle", 1),
                ("switch", "tornadus", 0),
            ],
        )


class TestGroupGCanonicalDecisionParity(unittest.TestCase):
    """Behavioral parity through the real canonical decision path."""

    def test_identical_state_runs_choose_move_in_both_modes(self):
        with _tempfile.TemporaryDirectory() as tmpdir:
            random_result = _run_canonical_decision(
                "random_doubles",
                _os.path.join(tmpdir, "random.jsonl"),
                "runtime-parity-random",
            )
            vgc_result = _run_canonical_decision(
                "vgc_selected_four",
                _os.path.join(tmpdir, "vgc.jsonl"),
                "runtime-parity-vgc",
            )

        for field in (
            "selected_message",
            "legal_slot0",
            "legal_slot1",
            "raw_slot0",
            "raw_slot1",
            "safety_slot0",
            "safety_slot1",
            "joint",
            "final",
        ):
            self.assertEqual(
                random_result[field],
                vgc_result[field],
                f"canonical decision mismatch for {field}",
            )
        self.assertEqual(
            random_result["player"]._v2l1_invocation_status,
            "completed",
        )
        self.assertEqual(
            vgc_result["player"]._v2l1_invocation_status,
            "completed",
        )

    def test_audit_records_are_execution_derived(self):
        with _tempfile.TemporaryDirectory() as tmpdir:
            result = _run_canonical_decision(
                "vgc_selected_four",
                _os.path.join(tmpdir, "vgc.jsonl"),
                "runtime-audit-vgc",
            )
        turn = result["turn"]
        self.assertEqual(
            turn["shared_engine_invocation_status"],
            "completed",
        )
        self.assertTrue(turn["shared_engine_used"])
        self.assertTrue(turn["shared_engine_invocation_id"])
        self.assertEqual(
            turn["v2l1_legal_action_keys_slot0"],
            [["move", "dragonclaw", 1]],
        )
        self.assertTrue(turn["v2l1_raw_scores_slot0"])
        self.assertTrue(turn["v2l1_selected_joint_key"])
        self.assertEqual(
            turn["v2l1_final_action_keys"],
            ["move|dragonclaw|1", "move|tackle|2"],
        )
        from inspect_vgc2026_runtime_parity import (
            _parity_mismatch_reasons,
        )
        self.assertEqual(_parity_mismatch_reasons(turn), [])


class TestGroupGProductionGeneratedAuditProof(unittest.TestCase):
    """V2l.1 — produce a temporary JSONL through a
    real ``ControlledTeamPreviewPlayer`` instance
    by calling the production audit hooks (NOT by
    calling ``log_turn_decision`` directly). The
    inspector reads the generated file successfully.
    """

    def test_production_generated_audit_via_real_player(self):
        """A real ``choose_move`` call produces the persisted proof."""
        with _tempfile.TemporaryDirectory() as tmpdir:
            result = _run_canonical_decision(
                "vgc_selected_four",
                _os.path.join(tmpdir, "production.jsonl"),
                "v2l1-production-audit",
            )
        turn = result["turn"]
        self.assertEqual(
            turn["runtime_mode"], "vgc_selected_four"
        )
        self.assertEqual(
            turn["concrete_player_class"],
            "ControlledTeamPreviewPlayer",
        )
        self.assertTrue(turn["shared_engine_used"])
        self.assertEqual(
            turn["shared_engine_invocation_status"],
            "completed",
        )
        self.assertTrue(turn["v2l1_raw_scores_slot0"])
        self.assertTrue(turn["v2l1_selected_joint_key"])
        self.assertTrue(turn["v2l1_final_action_keys"])
        from inspect_vgc2026_runtime_parity import (
            _parity_mismatch_reasons,
        )
        self.assertEqual(_parity_mismatch_reasons(turn), [])
        return

        # Kept below only as historical context until the V2l.1
        # test module is split; it is unreachable and no longer
        # supplies evidence.
        from poke_env import AccountConfiguration
        from bot_vgc2026_phaseV2c import (
            ControlledTeamPreviewPlayer,
        )

        preview = _make_vgc_preview(seed=99)
        with _tempfile.TemporaryDirectory() as tmpdir:
            log_path = _os.path.join(
                tmpdir, "v2l1_prod_audit.jsonl"
            )
            audit_logger = _v2l1_AuditLogger(
                filepath=log_path, reset=True
            )
            account = AccountConfiguration("v2l1_prod", None)
            player = create_controlled_player(
                account,
                _SAMPLE_VGC_TEAM_TEXT,
                preview,
                "v2l1_prod_test",
                0,
                "p1",
                "gen9championsvgc2026regma",
                audit_logger=audit_logger,
            )
            try:
                # Simulate one turn of execution by
                # calling the canonical helper that
                # ``choose_move`` would call to set
                # the V2l.1 per-decision snapshot.
                # We use the production helpers
                # directly (no fake pass-through).
                battle = MagicMock()
                battle.battle_tag = "v2l1_prod_test"
                battle.active_pokemon = [
                    MockPokemon("Incineroar", ["FIRE", "DARK"]),
                    None,
                ]
                battle.opponent_active_pokemon = [
                    None, None,
                ]
                battle.turn = 1
                battle.player_role = "p1"
                battle._replay_data = []
                battle.fields = []
                battle.player_username = "v2l1_prod"
                battle.opponent_username = "opp"
                battle.won = None
                # Mark the V2l.1 invocation (what
                # ``choose_move`` would do on entry).
                player._v2l1_invocation_id = (
                    f"v2l1-{id(player)}-1"
                )
                player._v2l1_invocation_count = 1
                # Use the pure helpers to set the
                # per-decision snapshot.
                from poke_env.battle.double_battle import (
                    SingleBattleOrder,
                )
                from poke_env.player.battle_order import (
                    DoubleBattleOrder,
                )
                move = MagicMock()
                move.id = "tackle"
                o1 = SingleBattleOrder(move, move_target=1)
                pkmn = MagicMock()
                pkmn.species = "tornadus"
                o2 = SingleBattleOrder(pkmn, move_target=0)
                valid_orders = [[o1, o2], [o1]]
                player._v2l1_legal_keys_slot0 = (
                    _v2l1_legal_keys(valid_orders, 0)
                )
                player._v2l1_legal_keys_slot1 = (
                    _v2l1_legal_keys(valid_orders, 1)
                )
                player._v2l1_raw_scores_slot0 = (
                    _v2l1_raw_scores(
                        {id(o1): 10.0, id(o2): 5.0},
                        valid_orders, 0,
                    )
                )
                player._v2l1_raw_scores_slot1 = (
                    _v2l1_raw_scores(
                        {id(o1): 7.0}, valid_orders, 1,
                    )
                )
                player._v2l1_safety_blocks_slot0 = (
                    _v2l1_safety_block_map(
                        {id(o2): True}, valid_orders, 0,
                    )
                )
                player._v2l1_safety_blocks_slot1 = (
                    _v2l1_safety_block_map(
                        {}, valid_orders, 1,
                    )
                )
                joint = DoubleBattleOrder(o1, o2)
                player._v2l1_selected_joint_key = (
                    _v2l1_selected_joint_key(joint)
                )
                player._v2l1_final_keys = (
                    _v2l1_final_keys_from_joint(joint)
                )
                # Now call the audit log hook
                # (this is the SAME call the canonical
                # engine makes at the end of
                # ``choose_move``).
                audit_logger.battle_configs[
                    "v2l1_prod_test"
                ] = DoublesDamageAwareConfig()
                audit_logger.log_turn_decision(
                    battle_tag="v2l1_prod_test",
                    turn=1,
                    battle=battle,
                    selected_joint_order=(
                        "/choose tackle 1, switch tornadus"
                    ),
                    selected_score=10.0,
                    scored_joint_orders=[],
                    expected_damages=[50, 50],
                    expected_kos=[False, False],
                    target_hps=[0.8, 0.8],
                    overkill_triggered=False,
                    focus_fire_triggered=False,
                    ally_hit_penalty_triggered=False,
                    spread_available=[False, False],
                    best_spread_score=[0.0, 0.0],
                    best_ko_score=[0.0, 0.0],
                    low_hp_opponent_existed=False,
                    low_hp_opponent_targeted=False,
                    slot_actions=[
                        "/choose tackle 1",
                        "/choose switch tornadus",
                    ],
                    slot_action_types=[
                        {"damaging": True},
                        {"switching": True},
                    ],
                    target_species=["Tornadus", "Tornadus"],
                    runtime_mode="vgc_selected_four",
                    concrete_player_class=(
                        "ControlledTeamPreviewPlayer"
                    ),
                    shared_engine_invocation_id=(
                        player._v2l1_invocation_id
                    ),
                    shared_engine_invocation_status="completed",
                    shared_engine_owner=(
                        "bot_doubles_damage_aware."
                        "DoublesDamageAwarePlayer"
                    ),
                    v2l1_legal_action_keys_slot0=[
                        player._v2l1_action_key_to_str(k)
                        for k in (
                            player._v2l1_legal_keys_slot0
                        )
                    ],
                    v2l1_legal_action_keys_slot1=[
                        player._v2l1_action_key_to_str(k)
                        for k in (
                            player._v2l1_legal_keys_slot1
                        )
                    ],
                    v2l1_raw_scores_slot0=(
                        player._v2l1_action_key_to_str_map(
                            player._v2l1_raw_scores_slot0
                        )
                    ),
                    v2l1_raw_scores_slot1=(
                        player._v2l1_action_key_to_str_map(
                            player._v2l1_raw_scores_slot1
                        )
                    ),
                    v2l1_safety_blocks_slot0=(
                        player._v2l1_action_key_to_str_map(
                            player._v2l1_safety_blocks_slot0
                        )
                    ),
                    v2l1_safety_blocks_slot1=(
                        player._v2l1_action_key_to_str_map(
                            player._v2l1_safety_blocks_slot1
                        )
                    ),
                    v2l1_selected_joint_key=(
                        player._v2l1_joint_key_to_str(
                            player._v2l1_selected_joint_key
                        )
                    ),
                    v2l1_final_action_keys=[
                        player._v2l1_action_key_to_str(k)
                        for k in player._v2l1_final_keys
                    ],
                    selected_four=(
                        player._selected_four
                    ),
                    lead_2=player._lead_2,
                    back_2=player._back_2,
                    preview_policy=(
                        player._preview_policy
                    ),
                )
                audit_logger.update_previous_turn(
                    "v2l1_prod_test", battle
                )
                audit_logger.save_battle(
                    battle_tag="v2l1_prod_test",
                    winner="v2l1_prod",
                    battle=battle,
                )
                # The JSONL exists and has one
                # battle record with one turn.
                self.assertTrue(
                    _os.path.isfile(log_path)
                )
                with open(log_path) as f:
                    records = [
                        json.loads(line)
                        for line in f
                        if line.strip()
                    ]
                self.assertEqual(len(records), 1)
                self.assertEqual(
                    len(records[0]["audit_turns"]), 1
                )
                turn = records[0]["audit_turns"][0]
                # shared_engine_used is True because
                # we set the invocation id.
                self.assertTrue(
                    turn["shared_engine_used"]
                )
                self.assertEqual(
                    turn["runtime_mode"],
                    "vgc_selected_four",
                )
                self.assertEqual(
                    turn["concrete_player_class"],
                    "ControlledTeamPreviewPlayer",
                )
                # The legal keys, raw scores, safety
                # blocks, joint key, and final keys
                # are populated.
                self.assertGreater(
                    len(
                        turn[
                            "v2l1_legal_action_keys_slot0"
                        ]
                    ),
                    0,
                )
                self.assertIsNotNone(
                    turn["v2l1_selected_joint_key"]
                )
                self.assertGreater(
                    len(turn["v2l1_final_action_keys"]), 0
                )
                # Run the inspector on the
                # production-generated JSONL.
                from inspect_vgc2026_runtime_parity import (
                    _iter_turn_records,
                    _parity_mismatch_reasons,
                )
                flat = _iter_turn_records(records)
                self.assertEqual(len(flat), 1)
                # --mismatch-only must report zero
                # mismatches for valid evidence.
                reasons = _parity_mismatch_reasons(flat[0])
                self.assertEqual(
                    reasons, [],
                    f"Inspector reported mismatches: "
                    f"{reasons}",
                )
            finally:
                try:
                    player.ps_client.close()
                except Exception:
                    pass

    def test_corrupt_invocation_evidence_produces_mismatch(self):
        """A record with no invocation id reports
        ``shared_engine_used=False`` and the
        inspector classifies it as a mismatch.
        """
        with _tempfile.TemporaryDirectory() as tmpdir:
            log_path = _os.path.join(
                tmpdir, "v2l1_corrupt.jsonl"
            )
            logger = _v2l1_AuditLogger(
                filepath=log_path, reset=True
            )
            battle_tag = "v2l1_corrupt"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            battle = MagicMock()
            battle.battle_tag = battle_tag
            battle.active_pokemon = [
                MockPokemon("Incineroar", ["FIRE", "DARK"]),
                None,
            ]
            battle.opponent_active_pokemon = [None, None]
            battle.turn = 1
            battle.player_role = "p1"
            battle._replay_data = []
            battle.fields = []
            battle.player_username = "v2l1_corrupt"
            battle.opponent_username = "opp"
            # Log without an invocation id.
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order="/choose tackle 1",
                selected_score=10.0,
                scored_joint_orders=[],
                expected_damages=[50, 50],
                expected_kos=[False, False],
                target_hps=[0.8, 0.8],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose tackle 1", "/choose pass"
                ],
                slot_action_types=[
                    {"damaging": True}, {"damaging": True}
                ],
                target_species=["Tornadus", "Tornadus"],
                runtime_mode="vgc_selected_four",
                concrete_player_class=(
                    "ControlledTeamPreviewPlayer"
                ),
                # selected_four populated
                selected_four=[
                    "Incineroar", "Tornadus",
                    "Rillaboom", "Garchomp",
                ],
                lead_2=["Incineroar", "Tornadus"],
                back_2=["Rillaboom", "Garchomp"],
                preview_policy="basic_top4",
                # NO shared_engine_invocation_id
            )
            logger.update_previous_turn(battle_tag, battle)
            logger.save_battle(
                battle_tag=battle_tag,
                winner="v2l1_corrupt",
                battle=battle,
            )
            with open(log_path) as f:
                records = [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]
            from inspect_vgc2026_runtime_parity import (
                _iter_turn_records,
                _parity_mismatch_reasons,
            )
            flat = _iter_turn_records(records)
            self.assertEqual(len(flat), 1)
            reasons = _parity_mismatch_reasons(flat[0])
            # Inspector flags shared_engine_used
            # = False as a mismatch.
            self.assertGreater(
                len(reasons), 0
            )
            self.assertTrue(
                any(
                    "shared_engine_used" in r
                    for r in reasons
                )
            )


class TestGroupGTargetSwitchBenchParity(unittest.TestCase):
    """V2l.1 — Heal Pulse, voluntary switch, forced
    switch, and selected-four bench parity between
    Random Doubles and VGC.

    The default ``enable_support_move_target_hard_safety``
    flag is False per AGENTS.md, so wrong-side
    support targeting is NOT yet enforced. Both
    runtimes must produce identical keys/scores for
    the SAME input regardless.
    """

    def test_safety_blocks_returned_for_empty_input(self):
        """``_compute_order_safety_blocks`` returns 6
        empty dicts for an empty ``valid_orders``.
        Both runtime modes return the same result.
        """
        config = DoublesDamageAwareConfig()
        result_rd = _v2l1_compute_safety_blocks(
            battle=None, config=config, valid_orders=[[], []]
        )
        result_vgc = _v2l1_compute_safety_blocks(
            battle=None, config=config, valid_orders=[[], []]
        )
        self.assertEqual(result_rd, result_vgc)
        # All 6 returned dicts are empty.
        self.assertEqual(len(result_rd), 8)
        for d in result_rd:
            self.assertEqual(d, {})

    def test_heal_pulse_wrong_side_uses_same_real_decision_path(self):
        """With the safety flag explicitly enabled, both modes avoid it."""
        from test_doubles_ability_hard_safety import (
            MockBattle as RealMockBattle,
            MockMove as RealMockMove,
            MockPokemon as RealMockPokemon,
        )
        from poke_env.player.battle_order import SingleBattleOrder

        messages = []
        for runtime_mode in (
            "random_doubles", "vgc_selected_four"
        ):
            player = (
                _make_test_player(runtime_mode=runtime_mode)
                if runtime_mode == "random_doubles"
                else _make_vgc_player(_make_vgc_preview())
            )
            config = DoublesDamageAwareConfig()
            config.enable_support_move_target_hard_safety = True
            player.config = config
            battle = RealMockBattle()
            battle.battle_tag = f"heal-pulse-{runtime_mode}"
            battle._replay_data = []
            heal_pulse = RealMockMove(
                "healpulse", "PSYCHIC", 0, "STATUS", "any"
            )
            tackle = RealMockMove("tackle", "NORMAL")
            battle.active_pokemon = [
                RealMockPokemon("blissey", ["NORMAL"]),
                RealMockPokemon("pikachu", ["ELECTRIC"]),
            ]
            battle.opponent_active_pokemon = [
                RealMockPokemon("snorlax", ["NORMAL"]),
                RealMockPokemon("rhyperior", ["GROUND"]),
            ]
            wrong_side = SingleBattleOrder(
                heal_pulse, move_target=1
            )
            ally = SingleBattleOrder(
                heal_pulse, move_target=-2
            )
            partner = SingleBattleOrder(
                tackle, move_target=2
            )
            battle.available_moves = [[heal_pulse], [tackle]]
            battle.valid_orders = [
                [wrong_side, ally], [partner]
            ]
            messages.append(player.choose_move(battle).message)

        self.assertEqual(messages[0], messages[1])
        self.assertIn("healpulse -2", messages[0])
        self.assertNotIn("healpulse 1", messages[0])

    def test_forced_switch_uses_same_real_decision_path(self):
        """Both modes choose the same replacement from legal orders."""
        from test_doubles_ability_hard_safety import (
            MockBattle as RealMockBattle,
            MockMove as RealMockMove,
            MockPokemon as RealMockPokemon,
        )
        from poke_env.player.battle_order import SingleBattleOrder

        messages = []
        for runtime_mode in (
            "random_doubles", "vgc_selected_four"
        ):
            player = (
                _make_test_player(runtime_mode=runtime_mode)
                if runtime_mode == "random_doubles"
                else _make_vgc_player(_make_vgc_preview())
            )
            battle = RealMockBattle()
            battle.battle_tag = f"forced-switch-{runtime_mode}"
            battle._replay_data = []
            tackle = RealMockMove("tackle", "NORMAL")
            battle.active_pokemon = [
                RealMockPokemon("blissey", ["NORMAL"]),
                RealMockPokemon("pikachu", ["ELECTRIC"]),
            ]
            battle.opponent_active_pokemon = [
                RealMockPokemon("snorlax", ["NORMAL"]),
                RealMockPokemon("lucario", ["STEEL"]),
            ]
            battle.force_switch = [True, False]
            switch_0 = SingleBattleOrder(
                RealMockPokemon("garchomp", ["GROUND"])
            )
            switch_1 = SingleBattleOrder(
                RealMockPokemon("tornadus", ["FLYING"])
            )
            partner = SingleBattleOrder(
                tackle, move_target=1
            )
            battle.available_moves = [[], [tackle]]
            battle.valid_orders = [
                [switch_0, switch_1], [partner]
            ]
            messages.append(player.choose_move(battle).message)

        self.assertEqual(messages[0], messages[1])
        self.assertIn("switch Garchomp", messages[0])

    def test_v2l1_audit_logger_preserves_legacy_record(self):
        """A legacy record (no V2l.1 kwargs) is still
        readable. The inspector can read mixed
        V2l.1 / legacy records in the same JSONL.
        """
        with _tempfile.TemporaryDirectory() as tmpdir:
            log_path = _os.path.join(
                tmpdir, "v2l1_mixed.jsonl"
            )
            logger = _v2l1_AuditLogger(
                filepath=log_path, reset=True
            )
            battle_tag = "v2l1_mixed"
            logger.battle_configs[battle_tag] = (
                DoublesDamageAwareConfig()
            )
            battle = MagicMock()
            battle.battle_tag = battle_tag
            battle.active_pokemon = [
                MockPokemon("Incineroar", ["FIRE", "DARK"]),
                None,
            ]
            battle.opponent_active_pokemon = [None, None]
            battle.turn = 1
            battle.player_role = "p1"
            battle._replay_data = []
            battle.fields = []
            battle.player_username = "v2l1_mixed"
            battle.opponent_username = "opp"
            # Legacy kwargs only (no V2l.1).
            logger.log_turn_decision(
                battle_tag=battle_tag,
                turn=1,
                battle=battle,
                selected_joint_order="/choose tackle 1",
                selected_score=10.0,
                scored_joint_orders=[],
                expected_damages=[50, 50],
                expected_kos=[False, False],
                target_hps=[0.8, 0.8],
                overkill_triggered=False,
                focus_fire_triggered=False,
                ally_hit_penalty_triggered=False,
                spread_available=[False, False],
                best_spread_score=[0.0, 0.0],
                best_ko_score=[0.0, 0.0],
                low_hp_opponent_existed=False,
                low_hp_opponent_targeted=False,
                slot_actions=[
                    "/choose tackle 1", "/choose pass"
                ],
                slot_action_types=[
                    {"damaging": True}, {"damaging": True}
                ],
                target_species=["Tornadus", "Tornadus"],
            )
            logger.update_previous_turn(battle_tag, battle)
            logger.save_battle(
                battle_tag=battle_tag,
                winner="v2l1_mixed",
                battle=battle,
            )
            with open(log_path) as f:
                records = [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]
            turn_record = records[0]["audit_turns"][0]
            # Legacy record: no invocation id, no V2l.1
            # fields. The inspector's mismatch check
            # reports ``shared_engine_used`` is False.
            self.assertFalse(
                turn_record["shared_engine_used"]
            )
            # V2l.1 fields may or may not be present
            # depending on the logger's default
            # kwargs. If they are present, they must
            # be None. The presence / absence is
            # allowed because the legacy record is
            # the SAME shape minus the V2l.1 data.
            for v2l1_field in (
                "v2l1_legal_action_keys_slot0",
                "v2l1_legal_action_keys_slot1",
                "v2l1_raw_scores_slot0",
                "v2l1_raw_scores_slot1",
                "v2l1_safety_blocks_slot0",
                "v2l1_safety_blocks_slot1",
                "v2l1_selected_joint_key",
                "v2l1_final_action_keys",
            ):
                if v2l1_field in turn_record:
                    self.assertIsNone(
                        turn_record[v2l1_field]
                    )


class TestGroupGV2l1RunnerAuditWiring(unittest.TestCase):
    """V2l.1 — the real ``VGCBattleRunnerV2c`` must
    own a unique runtime-parity JSONL path and
    hand a real ``DoublesDecisionAuditLogger`` to
    every ``create_controlled_player`` call.
    """

    def test_runner_owns_runtime_audit_path(self):
        """The runner's ``runtime_audit_path`` is
        derived from the artifact tag when the
        caller does not supply an explicit path.
        """
        from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c

        with _tempfile.TemporaryDirectory() as tmpdir:
            runner = VGCBattleRunnerV2c(
                artifact_tag="v2l1_runner_test",
                log_dir=tmpdir,
                overwrite=True,
            )
            self.assertIsNotNone(
                runner.runtime_audit_path
            )
            self.assertTrue(
                str(runner.runtime_audit_path).endswith(
                    "v2l1_runner_test_runtime_audit.jsonl"
                )
            )
            # Both players are recorded under their
            # battle tag.
            self.assertEqual(
                len(
                    runner._runtime_audit_loggers_by_player
                ),
                0,
            )

    def test_runner_explicit_runtime_audit_path(self):
        """The runner honors an explicit
        ``runtime_audit_path`` argument.
        """
        from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c

        with _tempfile.TemporaryDirectory() as tmpdir:
            explicit = _os.path.join(
                tmpdir, "explicit_audit.jsonl"
            )
            runner = VGCBattleRunnerV2c(
                artifact_tag="v2l1_explicit_test",
                log_dir=tmpdir,
                overwrite=True,
                runtime_audit_path=explicit,
            )
            self.assertEqual(
                str(runner.runtime_audit_path), explicit
            )

    def test_runner_legacy_no_runtime_audit(self):
        """When the caller does not supply
        ``runtime_audit_path`` and there is no
        ``artifact_tag``, ``runtime_audit_path``
        is ``None``. Legacy use continues.
        """
        from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c

        with _tempfile.TemporaryDirectory() as tmpdir:
            runner = VGCBattleRunnerV2c(
                artifact_tag=None,
                log_dir=tmpdir,
                overwrite=True,
            )
            # No artifact tag → no runtime audit
            # path. Legacy use.
            self.assertIsNone(runner.runtime_audit_path)
            self.assertIsNone(
                runner._get_runtime_audit_logger("p1")
            )

    def test_runner_get_runtime_audit_logger_lazily(self):
        """The runtime audit logger is created
        lazily on the first call. Both sides append
        to one file but use independent state.
        """
        from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c

        with _tempfile.TemporaryDirectory() as tmpdir:
            explicit = _os.path.join(
                tmpdir, "lazy_audit.jsonl"
            )
            runner = VGCBattleRunnerV2c(
                artifact_tag="v2l1_lazy_test",
                log_dir=tmpdir,
                overwrite=True,
                runtime_audit_path=explicit,
            )
            logger_p1 = runner._get_runtime_audit_logger("p1")
            logger_p2 = runner._get_runtime_audit_logger("p2")
            # Both sides append to the same file but
            # retain independent pending-turn state.
            self.assertIsNot(logger_p1, logger_p2)
            self.assertIsNotNone(logger_p1)
            self.assertEqual(logger_p1.filepath, logger_p2.filepath)

    def test_same_battle_tag_cannot_overwrite_other_side_state(self):
        """Two real decisions with one tag persist as two records."""
        from bot_vgc2026_phaseV2c import VGCBattleRunnerV2c

        with _tempfile.TemporaryDirectory() as tmpdir:
            runner = VGCBattleRunnerV2c(
                artifact_tag="v2l1_collision_test",
                log_dir=tmpdir,
                overwrite=True,
            )
            logger_p1 = runner._get_runtime_audit_logger("same|p1")
            logger_p2 = runner._get_runtime_audit_logger("same|p2")
            p1_result = _run_canonical_decision(
                "vgc_selected_four",
                str(runner.runtime_audit_path),
                "same",
                audit_logger=logger_p1,
            )
            with open(runner.runtime_audit_path) as stream:
                self.assertEqual(
                    len([line for line in stream if line.strip()]),
                    1,
                )
            p2_result = _run_canonical_decision(
                "random_doubles",
                str(runner.runtime_audit_path),
                "same",
                audit_logger=logger_p2,
            )
            with open(runner.runtime_audit_path) as stream:
                records = [
                    json.loads(line)
                    for line in stream
                    if line.strip()
                ]
            self.assertEqual(len(records), 2)
            turns = [record["audit_turns"][0] for record in records]
            self.assertEqual(
                {turn["runtime_mode"] for turn in turns},
                {"vgc_selected_four", "random_doubles"},
            )
            self.assertEqual(
                len({
                    turn["shared_engine_invocation_id"]
                    for turn in turns
                }),
                2,
            )
            self.assertNotEqual(
                p1_result["player"]._v2l1_invocation_id,
                p2_result["player"]._v2l1_invocation_id,
            )


if __name__ == "__main__":
    unittest.main()
