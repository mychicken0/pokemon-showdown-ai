"""Tests for PHASE7_POLICY_GAP_PSYCHIC_TERRAIN_PRIORITY_BLOCK_FIX.

Ponytail: pure unit tests. No poke-env runtime, no network,
no battles, no GPU. Mirrors the structure of
``test_phase7_fix_level_and_fakeout.py`` and
``test_phase7_fix_self_target_scoring.py``.
"""
import poke_env_test_cleanup  # noqa: F401
import json
import os
import unittest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

import showdown_ai.bot_doubles_damage_aware as bot
from showdown_ai.bot_doubles_damage_aware import (
    _is_priority_blocked_by_psychic_terrain,
    _is_fake_out_first_turn_only,
    _is_same_side_single_target_damage_blocked,
)
from showdown_ai.rl_data_3b_ff_monitor_v2 import (
    parse_priority_terrain_blocks_from_raw_protocol,
    stage2_gate_passes,
)


# ---- Fixtures ----


class _Order:
    def __init__(self, inner=None, move_target=0):
        self.order = inner
        self.move_target = move_target


class _Move:
    def __init__(self, move_id="", category="physical", target="normal", priority=0):
        self.id = move_id
        self._category = category
        self._target = target
        self.priority = priority

    @property
    def category(self):
        return self._category


class _Terrain:
    def __init__(self, name):
        self.name = name


class _Pokemon:
    def __init__(self, name="Tornadus", types=("Flying",), item=None, first_turn=False):
        self.name = name
        self.species = name
        self.types = list(types)
        self.item = item
        self.first_turn = first_turn
        self.fainted = False


class _Battle:
    def __init__(self, fields=None, opp=(None, None), ally=(None, None)):
        self.fields = fields or []
        self.opponent_active_pokemon = list(opp) + [None] * (2 - len(opp))
        self.active_pokemon = list(ally) + [None] * (2 - len(ally))


def _psy_terrain_battle(target=None):
    return _Battle(
        fields=[_Terrain("psychicterrain")],
        opp=(target, None),
        ally=(_Pokemon("Incineroar", types=("Fire",), first_turn=True), None),
    )


# ---- Scorer tests ----


class TestScorerBlocksFakeOutIntoPsychicTerrain(unittest.TestCase):
    def test_fake_out_into_psychic_terrain_blocks(self):
        # Opponent Volcarona (grounded: Fire/Bug, no item)
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_fake_out_first_turn_with_no_terrain_is_not_blocked_by_terrain_rule(self):
        # No Psychic Terrain, no terrain rule should fire.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _Battle(
            fields=[],
            opp=(target, None),
            ally=(_Pokemon("Incineroar", types=("Fire",), first_turn=True), None),
        )
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_fake_out_after_first_active_turn_still_blocked(self):
        # Existing Fake Out first-turn rule still applies.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        battle.active_pokemon[0] = _Pokemon("Incineroar", first_turn=False)
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        # Both rules block
        self.assertTrue(_is_fake_out_first_turn_only(order, battle, 0))
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_extreme_speed_into_psychic_terrain_blocks(self):
        target = _Pokemon("Arcanine", types=("Fire",), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("extremespeed", "physical", "normal", priority=2), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestNonPriorityMovesUnaffected(unittest.TestCase):
    def test_psychic_into_terrain_unaffected(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("psychic", "special", "normal", priority=0), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_dragon_claw_unaffected(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("dragonclaw", "physical", "normal", priority=0), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_flare_blitz_unaffected(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("flareblitz", "physical", "normal", priority=0), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_moonblast_unaffected(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("moonblast", "special", "normal", priority=0), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_protect_unaffected(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("protect", "status", "self", priority=4), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_switch_unaffected(self):
        # A switch is not a move; the helper returns False on no .id.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=object(), move_target=0)  # no .id attribute
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_pass_unaffected(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("pass", "status", "self", priority=0), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestSelfOrAllyTargetUnaffected(unittest.TestCase):
    def test_priority_targeting_ally_not_blocked(self):
        # Priority move targeting ally should NOT be blocked even
        # under Psychic Terrain; the rule is opponent-only.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestExistingSafetyPreserved(unittest.TestCase):
    def test_same_side_damage_block_still_works(self):
        # Same-side single-target damaging move should still be blocked
        # by the pre-existing helper, independent of terrain.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(
            inner=_Move("crunch", "physical", "normal", priority=0), move_target=-1
        )
        self.assertTrue(_is_same_side_single_target_damage_blocked(order))


class TestNoSpeciesBasedInference(unittest.TestCase):
    def test_no_magic_bounce_species_inference(self):
        # The helper must not call any species->ability resolver.
        # We just exercise it on a typical Psychic-type target
        # (e.g. Espeon) without an explicit item and confirm it
        # still blocks, because the conservative rule is to block
        # when groundedness is not explicit.
        target = _Pokemon("Espeon", types=("Psychic",), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_no_levitate_species_inference_when_types_listed(self):
        # If the poke-env types list shows Flying, the helper
        # accepts the target as ungrounded ONLY via the explicit
        # types check, not by inferring Levitate.
        target = _Pokemon("Gholdengo", types=("Steel", "Ghost"), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        # Gholdengo is not Flying, so the terrain rule still blocks.
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_flying_type_target_via_types_not_species(self):
        # If the battle state's types property says Flying, the
        # helper must allow the priority move through (the
        # groundedness check is types-based, not species-based).
        target = _Pokemon("Tornadus", types=("Flying",), item=None)
        battle = _psy_terrain_battle(target=target)
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestNoTerrainMeansNoBlock(unittest.TestCase):
    def test_no_terrain_priority_passes_through(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _Battle(
            fields=[],
            opp=(target, None),
            ally=(_Pokemon("Incineroar", types=("Fire",), first_turn=True), None),
        )
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_other_terrain_does_not_block(self):
        # Grassy / Electric / Misty terrain should not trigger the
        # Psychic Terrain priority block.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        battle = _Battle(
            fields=[_Terrain("grassyterrain")],
            opp=(target, None),
            ally=(_Pokemon("Incineroar", types=("Fire",), first_turn=True), None),
        )
        order = _Order(inner=_Move("fakeout", "physical", "normal", priority=3), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


# ---- Raw protocol parser / gate tests ----


class TestRawParserDetectsFakeOutIntoPsychicTerrain(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_ptb_test_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")
        with open(self.battle, "w") as f:
            f.write(json.dumps({"line": "|turn|4"}) + "\n")
            f.write(json.dumps({"line": "|move|p2a: Incineroar|Fake Out|p1b: Volcarona"}) + "\n")
            f.write(json.dumps({"line": "|-activate|p1b: Volcarona|move: Psychic Terrain"}) + "\n")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def test_fake_out_block_increments_count(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["fake_out_psychic_terrain_block_count"], 1)
        self.assertEqual(out["priority_terrain_block_count"], 1)
        self.assertEqual(out["failed_move_policy_bug_count"], 1)
        self.assertEqual(out["priority_terrain_block_battles"], 1)
        self.assertEqual(out["events"][0]["classification"], "POLICY_BUG_FAKE_OUT_IN_PSYCHIC_TERRAIN")
        self.assertFalse(out["priority_terrain_block_gate_pass"])
        self.assertFalse(out["failed_move_policy_gate_pass"])


class TestRawParserDetectsOtherPriorityBlocks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_ptb_test_es_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")
        with open(self.battle, "w") as f:
            f.write(json.dumps({"line": "|turn|3"}) + "\n")
            f.write(json.dumps({"line": "|move|p1a: Arcanine|Extreme Speed|p2a: Incineroar"}) + "\n")
            f.write(json.dumps({"line": "|-activate|p2a: Incineroar|move: Psychic Terrain"}) + "\n")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def test_extreme_speed_block_increments_count(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["priority_psychic_terrain_block_count"], 1)
        self.assertEqual(out["fake_out_psychic_terrain_block_count"], 0)
        self.assertEqual(out["priority_terrain_block_count"], 1)
        self.assertEqual(out["events"][0]["classification"], "POLICY_BUG_PRIORITY_BLOCKED_BY_PSYCHIC_TERRAIN")


class TestRawParserIgnoresNormalMissesAndProtect(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_ptb_test_clean_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")
        with open(self.battle, "w") as f:
            f.write(json.dumps({"line": "|turn|2"}) + "\n")
            f.write(json.dumps({"line": "|move|p1a: Arcanine|Extreme Speed|p2a: Incineroar"}) + "\n")
            f.write(json.dumps({"line": "|-miss|p2a: Incineroar"}) + "\n")
            f.write(json.dumps({"line": "|move|p1b: Garchomp|Protect|p1b: Garchomp"}) + "\n")
            f.write(json.dumps({"line": "|move|p1b: Garchomp|Protect||[still]"}) + "\n")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def test_normal_miss_does_not_increment(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["priority_terrain_block_count"], 0)
        self.assertTrue(out["priority_terrain_block_gate_pass"])

    def test_repeated_protect_does_not_increment(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["priority_terrain_block_count"], 0)


class TestStage2GateFailsWhenPriorityBlocks(unittest.TestCase):
    def test_gate_fails_on_priority_terrain_block(self):
        summary = {
            "raw_protocol_logs_present": True,
            "opponent_confirmed_actual_friendly_fire_count": 0,
            "bot_confirmed_actual_friendly_fire_count": 0,
            "unknown_friendly_fire_suspect_count": 0,
            "priority_terrain_block_count": 1,
        }
        self.assertFalse(stage2_gate_passes(summary))

    def test_gate_passes_on_clean_summary(self):
        summary = {
            "raw_protocol_logs_present": True,
            "opponent_confirmed_actual_friendly_fire_count": 0,
            "bot_confirmed_actual_friendly_fire_count": 0,
            "unknown_friendly_fire_suspect_count": 0,
            "priority_terrain_block_count": 0,
        }
        self.assertTrue(stage2_gate_passes(summary))


class TestScreenshotRawSnippetIsClassified(unittest.TestCase):
    """The exact raw lines from battle-gen9doublescustomgame-102017
    turn 4 must be classified as
    POLICY_BUG_FAKE_OUT_IN_PSYCHIC_TERRAIN.
    """

    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_ptb_test_screenshot_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")
        with open(self.battle, "w") as f:
            f.write(json.dumps({"line": "|turn|4"}) + "\n")
            f.write(json.dumps({"line": "|move|p2a: Incineroar|Fake Out|p1b: Volcarona"}) + "\n")
            f.write(json.dumps({"line": "|-activate|p1b: Volcarona|move: Psychic Terrain"}) + "\n")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def test_screenshot_classified_as_fake_out_in_psychic_terrain(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(len(out["events"]), 1)
        ev = out["events"][0]
        self.assertEqual(ev["classification"], "POLICY_BUG_FAKE_OUT_IN_PSYCHIC_TERRAIN")
        self.assertEqual(ev["actor"], "p2a: Incineroar")
        self.assertEqual(ev["target"], "p1b: Volcarona")
        self.assertEqual(ev["move"], "Fake Out")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Prankster extension tests.
# ---------------------------------------------------------------------------


class _StatusMove:
    def __init__(self, move_id="", target="normal", priority=0):
        self.id = move_id
        self._target = target
        self.priority = priority
        self._category_name = "STATUS"

    @property
    def category(self):
        class _Cat:
            name = "STATUS"
        return _Cat()


def _prankster_battle(target=None, user=None):
    fields = [_Terrain("psychicterrain")]
    opp = [target] + [None, None]
    ally = [user] + [None, None]
    return _Battle(fields=fields, opp=opp, ally=ally)


class TestPranksterOpponentStatusBlocked(unittest.TestCase):
    def test_prankster_taunt_into_opponent_blocked(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        user = _Pokemon("Tornadus", types=("Flying",), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("taunt"), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_prankster_encore_into_opponent_blocked(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        user = _Pokemon("Whimsicott", types=("Grass", "Fairy"), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("encore"), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_prankster_thunder_wave_into_opponent_blocked(self):
        target = _Pokemon("Garchomp", types=("Dragon", "Ground"), item=None)
        user = _Pokemon("Tornadus", types=("Flying",), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("thunderwave"), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_prankster_will_o_wisp_into_opponent_blocked(self):
        target = _Pokemon("Garchomp", types=("Dragon", "Ground"), item=None)
        user = _Pokemon("Sableye", types=("Dark", "Ghost"), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("willowisp"), move_target=0)
        self.assertTrue(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestNonPranksterStatusNotBlocked(unittest.TestCase):
    def test_non_prankster_taunt_not_blocked(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        user = _Pokemon("Garchomp", types=("Dragon", "Ground"), item=None)
        user.ability = "roughskin"  # not Prankster
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("taunt"), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_unknown_ability_not_treated_as_prankster(self):
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        user = _Pokemon("Tornadus", types=("Flying",), item=None)
        # no .ability attribute at all
        if hasattr(user, "ability"):
            del user.ability
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("taunt"), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_species_alone_does_not_count(self):
        # A common Prankster species (Whimsicott) without an
        # explicit ability attribute must NOT be treated as
        # Prankster.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        user = _Pokemon("Whimsicott", types=("Grass", "Fairy"), item=None)
        if hasattr(user, "ability"):
            del user.ability
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("taunt"), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestPranksterSelfSideSupportUnaffected(unittest.TestCase):
    def test_prankster_tailwind_targeting_self_not_blocked(self):
        user = _Pokemon("Tornadus", types=("Flying",), item=None)
        user.ability = "prankster"
        # Target is self/ally (move_target < 0). Helper must return False.
        target_self = _Pokemon("Whimsicott", types=("Grass", "Fairy"), item=None)
        battle = _prankster_battle(target=target_self, user=user)
        order = _Order(inner=_StatusMove("tailwind"), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_prankster_reflect_targeting_self_not_blocked(self):
        user = _Pokemon("Whimsicott", types=("Grass", "Fairy"), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=None, user=user)
        order = _Order(inner=_StatusMove("reflect"), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_prankster_light_screen_targeting_self_not_blocked(self):
        user = _Pokemon("Whimsicott", types=("Grass", "Fairy"), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=None, user=user)
        order = _Order(inner=_StatusMove("lightscreen"), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestQuickGuardAndProtectNotBlocked(unittest.TestCase):
    def test_quick_guard_self_not_blocked(self):
        user = _Pokemon("Incineroar", types=("Fire",), item=None)
        user.ability = "intimidate"
        battle = _prankster_battle(target=None, user=user)
        order = _Order(inner=_Move("quickguard", "status", "self", priority=3), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))

    def test_protect_self_not_blocked(self):
        user = _Pokemon("Incineroar", types=("Fire",), item=None)
        battle = _prankster_battle(target=None, user=user)
        order = _Order(inner=_Move("protect", "status", "self", priority=4), move_target=-1)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestPranksterUngroundedTargetUnaffected(unittest.TestCase):
    def test_prankster_status_into_flying_target_not_blocked(self):
        # Target Tornadus is explicitly Flying; Psychic Terrain
        # does not block priority against ungrounded.
        target = _Pokemon("Tornadus", types=("Flying",), item=None)
        user = _Pokemon("Sableye", types=("Dark", "Ghost"), item=None)
        user.ability = "prankster"
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("taunt"), move_target=0)
        self.assertFalse(_is_priority_blocked_by_psychic_terrain(order, battle, 0))


class TestPranksterRawParser(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_prankster_test_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")
        with open(self.battle, "w") as f:
            f.write(json.dumps({"line": "|turn|5"}) + "\n")
            f.write(json.dumps({"line": "|-ability|p2a: Tornadus|Prankster"}) + "\n")
            f.write(json.dumps({"line": "|move|p2a: Tornadus|Taunt|p1a: Volcarona"}) + "\n")
            f.write(json.dumps({"line": "|-activate|p1a: Volcarona|move: Psychic Terrain"}) + "\n")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def test_confirmed_prankster_block_count(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["prankster_psychic_terrain_block_count"], 1)
        self.assertEqual(out["priority_terrain_block_count"], 1)
        self.assertEqual(out["failed_move_policy_bug_count"], 1)
        self.assertEqual(out["unknown_prankster_psychic_terrain_suspect_count"], 0)
        ev = out["events"][0]
        self.assertEqual(ev["classification"], "POLICY_BUG_PRANKSTER_STATUS_IN_PSYCHIC_TERRAIN")
        self.assertTrue(ev["ability_known"])
        self.assertFalse(out["prankster_priority_block_gate_pass"])

    def test_stage2_gate_fails_on_confirmed_prankster(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        from showdown_ai.rl_data_3b_ff_monitor_v2 import make_empty_summary
        summary = make_empty_summary(raw_protocol_logs_present=True)
        summary.update({
            "priority_terrain_block_count": out["priority_terrain_block_count"],
            "prankster_psychic_terrain_block_count": out["prankster_psychic_terrain_block_count"],
            "unknown_prankster_psychic_terrain_suspect_count": out["unknown_prankster_psychic_terrain_suspect_count"],
            "failed_move_policy_bug_count": out["failed_move_policy_bug_count"],
        })
        from showdown_ai.rl_data_3b_ff_monitor_v2 import stage2_gate_passes
        self.assertFalse(stage2_gate_passes(summary))


class TestUnknownPranksterSuspect(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.join("/tmp", "phase7_prankster_unk_" + str(os.getpid()))
        os.makedirs(self.tmpdir, exist_ok=True)
        self.battle = os.path.join(self.tmpdir, "battle-1.jsonl")
        with open(self.battle, "w") as f:
            f.write(json.dumps({"line": "|turn|5"}) + "\n")
            # No |-ability|...|Prankster reveal.
            f.write(json.dumps({"line": "|move|p2a: Tornadus|Taunt|p1a: Volcarona"}) + "\n")
            f.write(json.dumps({"line": "|-activate|p1a: Volcarona|move: Psychic Terrain"}) + "\n")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_prankster_does_not_count_as_confirmed(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        self.assertEqual(out["prankster_psychic_terrain_block_count"], 0)
        self.assertEqual(out["unknown_prankster_psychic_terrain_suspect_count"], 1)
        ev = out["events"][0]
        self.assertEqual(ev["classification"], "UNKNOWN_PRANKSTER_PRIORITY_NEEDS_ABILITY_EVIDENCE")
        self.assertFalse(ev["ability_known"])

    def test_unknown_prankster_suspect_fails_gate(self):
        out = parse_priority_terrain_blocks_from_raw_protocol(self.tmpdir)
        from showdown_ai.rl_data_3b_ff_monitor_v2 import make_empty_summary, stage2_gate_passes
        summary = make_empty_summary(raw_protocol_logs_present=True)
        summary.update({
            "priority_terrain_block_count": out["priority_terrain_block_count"],
            "prankster_psychic_terrain_block_count": out["prankster_psychic_terrain_block_count"],
            "unknown_prankster_psychic_terrain_suspect_count": out["unknown_prankster_psychic_terrain_suspect_count"],
            "failed_move_policy_bug_count": out["failed_move_policy_bug_count"],
        })
        self.assertFalse(stage2_gate_passes(summary))


class TestPranksterKnownUserKwarg(unittest.TestCase):
    def test_prankster_user_kwarg_works(self):
        # The scorer accepts a ``prankster_user`` test-only kwarg
        # so unit tests can simulate "ability explicitly known" when
        # the test battle mock has no ``.ability`` attribute.
        target = _Pokemon("Volcarona", types=("Bug", "Fire"), item=None)
        user = _Pokemon("Tornadus", types=("Flying",), item=None)
        if hasattr(user, "ability"):
            del user.ability
        battle = _prankster_battle(target=target, user=user)
        order = _Order(inner=_StatusMove("taunt"), move_target=0)
        self.assertTrue(
            _is_priority_blocked_by_psychic_terrain(
                order, battle, 0, prankster_user=True
            )
        )
        # Without the kwarg, the same battle should NOT block.
        self.assertFalse(
            _is_priority_blocked_by_psychic_terrain(order, battle, 0)
        )


class TestGatePassesOnCleanSummary(unittest.TestCase):
    def test_clean_summary_passes(self):
        from showdown_ai.rl_data_3b_ff_monitor_v2 import make_empty_summary, stage2_gate_passes
        s = make_empty_summary(raw_protocol_logs_present=True)
        # All counts default to 0. Gate should pass.
        self.assertTrue(stage2_gate_passes(s))
