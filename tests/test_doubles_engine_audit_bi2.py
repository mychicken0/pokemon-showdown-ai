"""Phase BI-2B: persisted per-turn state snapshot tests.

Validates that ``state_snapshot`` is captured in the
persisted audit JSONL and live JSONL, and that it
contains only visible, JSON-safe primitives (no
hidden info, no raw objects, no crash on missing
attributes).

These tests do NOT require a running Showdown server.
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _cleanup(paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def _make_logger(detail_level="top5"):
    """Construct a fresh audit logger with isolated
    temp files for the main and live event JSONLs.
    """
    with tempfile.NamedTemporaryFile(
        suffix=".jsonl", delete=False
    ) as f:
        main_path = f.name
    with tempfile.NamedTemporaryFile(
        suffix=".live.jsonl", delete=False
    ) as f:
        live_path = f.name
    from doubles_decision_audit_logger import (
        DoublesDecisionAuditLogger,
    )
    logger = DoublesDecisionAuditLogger(
        filepath=main_path,
        reset=True,
        detail_level=detail_level,
        live_event_filepath=live_path,
    )
    return logger, main_path, live_path


class _FakePokemon:
    """Minimal stand-in for ``poke_env.battle.pokemon.Pokemon``
    that supports the attribute names touched by
    ``_build_compact_state_snapshot``.
    """

    def __init__(self, species=None, hp_fraction=None, types=None,
                 current_hp=None, max_hp=None):
        self.species = species
        self._hp_fraction = hp_fraction
        self._types = types or []
        self.current_hp = current_hp
        self.max_hp = max_hp

    @property
    def current_hp_fraction(self):
        return self._hp_fraction

    @property
    def types(self):
        return self._types

    @property
    def type_1(self):
        return self._types[0] if self._types else None

    @property
    def type_2(self):
        return self._types[1] if len(self._types) > 1 else None


class _FakeType:
    """Minimal enum-like stand-in for
    ``poke_env.battle.pokemon_type.PokemonType``.
    """

    def __init__(self, name):
        self.name = name


class _FakeBattle:
    """Minimal Battle stand-in."""

    def __init__(self, turn=3, our=None, opp=None, weather=None,
                 fields=None, side_conditions=None,
                 opponent_side_conditions=None):
        self.turn = turn
        self.active_pokemon = our or [None, None]
        self.opponent_active_pokemon = opp or [None, None]
        self.weather = weather if weather is not None else {}
        self.fields = fields if fields is not None else {}
        self.side_conditions = (
            side_conditions if side_conditions is not None else {}
        )
        self.opponent_side_conditions = (
            opponent_side_conditions
            if opponent_side_conditions is not None else {}
        )


def _minimal_kwargs():
    """Minimal valid kwargs for log_turn_decision."""
    return dict(
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
    )


def _log_one(logger, battle):
    logger.completed_turns["tag"] = []
    logger.log_turn_decision(
        battle_tag="tag",
        turn=3,
        battle=battle,
        selected_joint_order="pass",
        selected_score=0.0,
        **_minimal_kwargs(),
    )


class TestStateSnapshotDirect(unittest.TestCase):
    """Direct tests of the helper with fake Battle/Pokemon."""

    def test_helper_returns_expected_keys(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        battle = _FakeBattle(
            turn=2,
            our=[_FakePokemon("pikachu", 0.5,
                              [_FakeType("ELECTRIC")])],
            opp=[_FakePokemon("charizard", 0.8,
                              [_FakeType("FIRE"), _FakeType("FLYING")])],
        )
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-x"
        )
        expected_keys = {
            "turn", "battle_tag",
            "our_active_species", "opp_active_species",
            "our_active_hp_fraction", "opp_active_hp_fraction",
            "our_active_types", "opp_active_types",
            # Phase ITEM-2: ability/item/revealed-moves
            "our_active_ability", "opp_active_ability",
            "our_active_item", "opp_active_item",
            "our_active_moves_revealed",
            "opp_active_moves_revealed",
            "weather", "fields",
            "side_conditions", "opponent_side_conditions",
        }
        self.assertEqual(set(snap.keys()), expected_keys)

    def test_helper_slot_order_preserved(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        our = [
            _FakePokemon("pikachu", 0.5, [_FakeType("ELECTRIC")]),
            _FakePokemon("charizard", 0.8,
                         [_FakeType("FIRE"), _FakeType("FLYING")]),
        ]
        opp = [
            _FakePokemon("blastoise", 0.3, [_FakeType("WATER")]),
            _FakePokemon("venusaur", 0.6,
                         [_FakeType("GRASS"), _FakeType("POISON")]),
        ]
        battle = _FakeBattle(turn=1, our=our, opp=opp)
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-y"
        )
        self.assertEqual(
            snap["our_active_species"], ["pikachu", "charizard"]
        )
        self.assertEqual(
            snap["opp_active_species"], ["blastoise", "venusaur"]
        )
        self.assertEqual(
            snap["our_active_hp_fraction"], [0.5, 0.8]
        )
        self.assertEqual(
            snap["opp_active_hp_fraction"], [0.3, 0.6]
        )
        self.assertEqual(
            snap["our_active_types"],
            [["electric"], ["fire", "flying"]],
        )
        self.assertEqual(
            snap["opp_active_types"],
            [["water"], ["grass", "poison"]],
        )

    def test_helper_missing_pokemon_uses_safe_defaults(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        battle = _FakeBattle(turn=1)
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-z"
        )
        self.assertEqual(snap["our_active_species"], [None, None])
        self.assertEqual(snap["opp_active_species"], [None, None])
        self.assertEqual(
            snap["our_active_hp_fraction"], [None, None]
        )
        self.assertEqual(
            snap["opp_active_hp_fraction"], [None, None]
        )
        self.assertEqual(snap["our_active_types"], [[], []])
        self.assertEqual(snap["opp_active_types"], [[], []])

    def test_helper_battle_none_does_not_crash(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            None, "tag-n"
        )
        self.assertIsNone(snap["turn"])
        self.assertEqual(snap["battle_tag"], "tag-n")
        self.assertEqual(snap["our_active_species"], [None, None])

    def test_helper_pokemon_with_no_species_uses_none(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        pkmn = _FakePokemon(species=None, hp_fraction=None)
        battle = _FakeBattle(turn=1, our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-q"
        )
        # Species is None; HP fraction falls back to None
        # (no current_hp/max_hp supplied).
        self.assertEqual(snap["our_active_species"], [None, None])
        self.assertEqual(
            snap["our_active_hp_fraction"], [None, None]
        )
        self.assertEqual(snap["our_active_types"], [[], []])

    def test_helper_hp_fallback_from_current_over_max(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        pkmn = _FakePokemon(
            species="snorlax", hp_fraction=None,
            current_hp=120, max_hp=200,
        )
        battle = _FakeBattle(turn=1, our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-h"
        )
        self.assertEqual(snap["our_active_hp_fraction"][0], 0.6)

    def test_helper_weather_terrain_fields_serialized(self):
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        battle = _FakeBattle(
            turn=1,
            weather={_FakeType("RAINDANCE"): 5},
            fields={_FakeType("ELECTRIC_TERRAIN"): 5,
                    _FakeType("GRAVITY"): 5},
            side_conditions={_FakeType("REFLECT"): 5},
            opponent_side_conditions={_FakeType("LIGHTSCREEN"): 5},
        )
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-f"
        )
        self.assertIn("raindance", snap["weather"])
        self.assertIn("electric_terrain", snap["fields"])
        self.assertIn("gravity", snap["fields"])
        self.assertIn("reflect", snap["side_conditions"])
        self.assertIn("lightscreen", snap["opponent_side_conditions"])

    def test_helper_no_hidden_info(self):
        """The snapshot must not include EVs, nature,
        or any hidden meta.

        Phase ITEM-2 update: ability/item/moves
        ARE now captured for OUR active pokemon
        (visible by design — we know our own
        team). For the OPP slot, ability/item
        are only captured when revealed by
        protocol; moves are only revealed moves.
        Hidden meta (EVs, nature, base stats)
        must never appear.
        """
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        pkmn = _FakePokemon("pikachu", 0.5, [_FakeType("ELECTRIC")])
        # Add fields — for our own pokemon these
        # are visible and ARE captured.
        pkmn.ability = "static"
        pkmn.item = "lightball"
        pkmn.moves = ["thunderbolt", "volttackle"]
        pkmn.evs = {"hp": 0, "atk": 252}
        pkmn.nature = "jolly"
        battle = _FakeBattle(turn=1, our=[pkmn, None])
        snap = DoublesDecisionAuditLogger._build_compact_state_snapshot(
            battle, "tag-h"
        )
        # Our visible data IS captured.
        self.assertEqual(snap["our_active_ability"][0], "static")
        self.assertEqual(snap["our_active_item"][0], "lightball")
        # Flatten snapshot to check no forbidden keys.
        flat = json.dumps(snap)
        # EV / nature must not be exposed (hidden meta).
        self.assertNotIn("jolly", flat)
        self.assertNotIn("252", flat)
        self.assertNotIn("evs", flat)
        self.assertNotIn("nature", flat)


class TestStateSnapshotPersisted(unittest.TestCase):
    """End-to-end: log a turn, save, and assert the
    persisted JSONL contains state_snapshot with the
    expected primitives.
    """

    def test_persisted_main_jsonl_has_state_snapshot(self):
        logger, main_path, live_path = _make_logger()
        try:
            battle = _FakeBattle(
                turn=4,
                our=[_FakePokemon("pikachu", 0.5,
                                  [_FakeType("ELECTRIC")]),
                     _FakePokemon("charizard", 0.8,
                                  [_FakeType("FIRE"),
                                   _FakeType("FLYING")])],
                opp=[_FakePokemon("blastoise", 0.3,
                                  [_FakeType("WATER")]),
                     None],
                weather={_FakeType("RAINDANCE"): 3},
            )
            _log_one(logger, battle)

            class FB:
                player_username = "test"
                turn = 4
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            audit_turns = record["audit_turns"]
            self.assertGreaterEqual(len(audit_turns), 1)
            turn = audit_turns[0]
            self.assertIn("state_snapshot", turn)
            snap = turn["state_snapshot"]
            self.assertEqual(snap["turn"], 4)
            self.assertEqual(
                snap["our_active_species"], ["pikachu", "charizard"]
            )
            self.assertEqual(
                snap["our_active_hp_fraction"], [0.5, 0.8]
            )
            self.assertEqual(
                snap["our_active_types"],
                [["electric"], ["fire", "flying"]],
            )
            self.assertEqual(
                snap["opp_active_species"], ["blastoise", None]
            )
            self.assertEqual(
                snap["opp_active_types"], [["water"], []]
            )
            self.assertIn("raindance", snap["weather"])
        finally:
            _cleanup([main_path, live_path])

    def test_persisted_main_jsonl_snapshot_with_none_pokemon(self):
        """Missing active Pokemon must not crash and must
        use safe defaults (None species, None hp, [] types).
        """
        logger, main_path, live_path = _make_logger()
        try:
            battle = _FakeBattle(turn=1)
            _log_one(logger, battle)

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            snap = record["audit_turns"][0]["state_snapshot"]
            self.assertEqual(
                snap["our_active_species"], [None, None]
            )
            self.assertEqual(
                snap["our_active_hp_fraction"], [None, None]
            )
            self.assertEqual(snap["our_active_types"], [[], []])
        finally:
            _cleanup([main_path, live_path])

    def test_live_event_has_state_snapshot(self):
        logger, main_path, live_path = _make_logger()
        try:
            battle = _FakeBattle(
                turn=2,
                our=[_FakePokemon("pikachu", 0.5,
                                  [_FakeType("ELECTRIC")]),
                     None],
                opp=[_FakePokemon("charizard", 0.8,
                                  [_FakeType("FIRE")]),
                     None],
                fields={_FakeType("GRAVITY"): 5},
            )
            _log_one(logger, battle)

            with open(live_path) as f:
                lines = [l for l in f if l.strip()]
            self.assertGreater(len(lines), 0)
            # The first event is the decision event (live event
            # for log_turn_decision).
            event = json.loads(lines[0])
            self.assertIn("state_snapshot", event)
            snap = event["state_snapshot"]
            self.assertEqual(snap["turn"], 2)
            self.assertEqual(
                snap["our_active_species"], ["pikachu", None]
            )
            self.assertEqual(snap["our_active_hp_fraction"], [0.5, None])
            self.assertEqual(
                snap["our_active_types"], [["electric"], []]
            )
            self.assertIn("gravity", snap["fields"])
        finally:
            _cleanup([main_path, live_path])

    def test_persisted_state_snapshot_is_json_safe(self):
        """The whole snapshot must round-trip through
        ``json.dumps`` without errors.
        """
        logger, main_path, live_path = _make_logger()
        try:
            battle = _FakeBattle(
                turn=1,
                our=[_FakePokemon("pikachu", 0.5,
                                  [_FakeType("ELECTRIC")]),
                     _FakePokemon("snorlax", 0.0,
                                  [_FakeType("NORMAL")])],
                opp=[_FakePokemon("garchomp", 0.6,
                                  [_FakeType("DRAGON"),
                                   _FakeType("GROUND")]),
                     _FakePokemon("incineroar", 0.4,
                                  [_FakeType("FIRE"),
                                   _FakeType("DARK")])],
                weather={_FakeType("SUNNYDAY"): 5},
                fields={_FakeType("TRICK_ROOM"): 5},
                side_conditions={_FakeType("REFLECT"): 5,
                                 _FakeType("LIGHTSCREEN"): 5},
                opponent_side_conditions={
                    _FakeType("TAILWIND"): 5,
                    _FakeType("SPIKES"): 1,
                },
            )
            _log_one(logger, battle)

            class FB:
                player_username = "test"
                turn = 1
                active_pokemon = [None, None]
                opponent_active_pokemon = [None, None]

            logger.save_battle("tag", "test", FB())

            with open(main_path) as f:
                record = json.loads(f.readline())
            snap = record["audit_turns"][0]["state_snapshot"]
            # json.dumps must not raise.
            encoded = json.dumps(snap)
            decoded = json.loads(encoded)
            self.assertEqual(decoded["turn"], 1)
            self.assertEqual(
                decoded["our_active_species"],
                ["pikachu", "snorlax"],
            )
            self.assertEqual(
                decoded["opp_active_species"],
                ["garchomp", "incineroar"],
            )
            self.assertEqual(
                decoded["our_active_hp_fraction"], [0.5, 0.0]
            )
            self.assertIn("sunnyday", decoded["weather"])
            self.assertIn("trick_room", decoded["fields"])
        finally:
            _cleanup([main_path, live_path])


class TestNoProductionCleanupImport(unittest.TestCase):
    """Sanity: production modules must not import
    ``poke_env_test_cleanup``.
    """

    def test_logger_does_not_import_cleanup(self):
        import doubles_decision_audit_logger as m
        with open(m.__file__) as f:
            content = f.read()
        self.assertNotIn("import poke_env_test_cleanup", content)
        self.assertNotIn("from poke_env_test_cleanup", content)


if __name__ == "__main__":
    unittest.main()
