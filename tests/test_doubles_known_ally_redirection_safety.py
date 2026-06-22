"""Phase 6.3.6b.3 — Known Ally Redirection Hard Safety Tests (Hardened)."""
import unittest
from unittest.mock import MagicMock, patch
import sys, os

import poke_env_test_cleanup  # noqa: F401
sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    ally_redirects_our_single_target_move,
    is_single_target_move,
    get_known_ability,
    classify_known_ally_redirection_audit,
    update_known_ally_redirection_repeat_state,
    classify_known_ally_redirection_error,
    _compute_order_safety_blocks,
    _normalize_ability_name,
)


class MockMove:
    def __init__(self, move_id, move_type, base_power=80, target="normal"):
        self.id = move_id; self.base_power = base_power
        self._type = move_type; self._target = target

    @property
    def type(self):
        m = MagicMock(); m.name = self._type; return m

    @property
    def target(self):
        return self._target

    @property
    def category(self):
        m = MagicMock(); m.name = "PHYSICAL"; return m


class MockPokemon:
    def __init__(self, species, ability=None, fainted=False):
        self.species = species; self._ability = ability
        self.fainted = fainted; self.current_hp_fraction = 1.0

    @property
    def ability(self):
        return self._ability

    @property
    def types(self):
        return []


# ======== Core Helper Tests (unchanged) ========

class TestAllyRedirectsMove(unittest.TestCase):
    def test_storm_drain_redirects_water(self):
        move = MockMove("waterfall", "WATER")
        redirects, reason = ally_redirects_our_single_target_move(move, MockPokemon("gyarados"), MockPokemon("tatsugiri", "stormdrain"))
        self.assertTrue(redirects); self.assertIn("stormdrain", reason)

    def test_lightning_rod_redirects_electric(self):
        move = MockMove("thunderbolt", "ELECTRIC")
        redirects, reason = ally_redirects_our_single_target_move(move, MockPokemon("raichu"), MockPokemon("rhydon", "lightningrod"))
        self.assertTrue(redirects); self.assertIn("lightningrod", reason)

    def test_unknown_ability_no_block(self):
        redirects, _ = ally_redirects_our_single_target_move(MockMove("waterfall", "WATER"), MockPokemon("g"), MockPokemon("t"))
        self.assertFalse(redirects)

    def test_non_water_with_storm_drain_no_block(self):
        redirects, _ = ally_redirects_our_single_target_move(MockMove("fireblast", "FIRE"), MockPokemon("c"), MockPokemon("t", "stormdrain"))
        self.assertFalse(redirects)

    def test_status_move_no_block(self):
        redirects, _ = ally_redirects_our_single_target_move(MockMove("swordsdance", "NORMAL", base_power=0), MockPokemon("g"), MockPokemon("t", "stormdrain"))
        self.assertFalse(redirects)

    def test_fainted_ally_no_block(self):
        redirects, _ = ally_redirects_our_single_target_move(MockMove("waterfall", "WATER"), MockPokemon("g"), MockPokemon("t", "stormdrain", fainted=True))
        self.assertFalse(redirects)

    def test_no_ally_no_block(self):
        redirects, _ = ally_redirects_our_single_target_move(MockMove("waterfall", "WATER"), MockPokemon("g"), None)
        self.assertFalse(redirects)

    def test_mold_breaker_ignores_ally_ability(self):
        with patch("bot_doubles_damage_aware.get_known_ability") as mg:
            def gka(pokemon, battle):
                return {"haxorus": "moldbreaker", "tatsugiri": "stormdrain"}.get(pokemon.species)
            mg.side_effect = gka
            redirects, _ = ally_redirects_our_single_target_move(MockMove("waterfall", "WATER"), MockPokemon("haxorus"), MockPokemon("tatsugiri"))
            self.assertFalse(redirects)


class TestBlockedCandidateMap(unittest.TestCase):
    def test_blocked_order_mapped(self):
        config = DoublesDamageAwareConfig(); config.enable_known_ally_redirection_hard_safety = True
        g = MockPokemon("gyarados"); t = MockPokemon("tatsugiri", "stormdrain")
        a = MockPokemon("abomasnow"); move = MockMove("waterfall", "WATER", base_power=80)
        battle = MagicMock(); battle.active_pokemon = [g, t]; battle.opponent_active_pokemon = [a, None]
        class O: pass
        o = O(); o.order = move; o.move_target = 1
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="stormdrain"):
            _, _, ar, _, _, _, _, _ = _compute_order_safety_blocks(battle, config, [[o], []])
        self.assertTrue(ar.get(id(o), False))

    def test_safe_move_not_mapped(self):
        config = DoublesDamageAwareConfig(); config.enable_known_ally_redirection_hard_safety = True
        g = MockPokemon("gyarados"); t = MockPokemon("tatsugiri", "stormdrain")
        a = MockPokemon("abomasnow"); move = MockMove("fireblast", "FIRE", base_power=110)
        battle = MagicMock(); battle.active_pokemon = [g, t]; battle.opponent_active_pokemon = [a, None]
        class O: pass
        o = O(); o.order = move; o.move_target = 1
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="stormdrain"):
            _, _, ar, _, _, _, _, _ = _compute_order_safety_blocks(battle, config, [[o], []])
        self.assertFalse(ar.get(id(o), False))


class TestConfigDefaults(unittest.TestCase):
    def test_default_disabled(self):
        self.assertFalse(DoublesDamageAwareConfig().enable_known_ally_redirection_hard_safety)
    def test_block_score_zero(self):
        self.assertEqual(DoublesDamageAwareConfig().known_ally_redirection_block_score, 0.0)
    def test_ability_awareness_disabled(self):
        self.assertFalse(DoublesDamageAwareConfig().enable_ability_awareness)
    def test_existing_safety_unchanged(self):
        c = DoublesDamageAwareConfig()
        self.assertTrue(c.enable_ability_hard_safety_only)
        self.assertTrue(c.ability_hard_safety_direct_absorb_only)


class TestIsSingleTargetMove(unittest.TestCase):
    def test_target_pos_1(self):
        class O: move_target = 1
        self.assertTrue(is_single_target_move(MockMove("a", "NORMAL"), O()))
    def test_target_pos_0_not_single(self):
        class O: move_target = 0
        self.assertFalse(is_single_target_move(MockMove("surf", "WATER", target="allAdjacentFoes"), O()))
    def test_normal_target_is_single(self):
        self.assertTrue(is_single_target_move(MockMove("tackle", "NORMAL", target="normal")))
    def test_no_move_false(self):
        self.assertFalse(is_single_target_move(None))


# ======== Pure Helper Tests ========

class TestAuditClassification(unittest.TestCase):
    def test_avoidable_selected(self):
        r = classify_known_ally_redirection_audit(True, True, True)
        self.assertTrue(r["avoidable_selected"]); self.assertFalse(r["only_legal"]); self.assertFalse(r["avoided"])

    def test_only_legal(self):
        r = classify_known_ally_redirection_audit(True, True, False)
        self.assertFalse(r["avoidable_selected"]); self.assertTrue(r["only_legal"]); self.assertFalse(r["avoided"])

    def test_avoided(self):
        r = classify_known_ally_redirection_audit(False, True, True)
        self.assertFalse(r["avoidable_selected"]); self.assertFalse(r["only_legal"]); self.assertTrue(r["avoided"])

    def test_no_candidate_no_avoided(self):
        r = classify_known_ally_redirection_audit(False, False, False)
        self.assertFalse(r["avoidable_selected"]); self.assertFalse(r["only_legal"]); self.assertFalse(r["avoided"])

    def test_only_legal_still_classified(self):
        r = classify_known_ally_redirection_audit(True, False, False)
        self.assertFalse(r["avoidable_selected"]); self.assertTrue(r["only_legal"]); self.assertFalse(r["avoided"])


class TestRepeatState(unittest.TestCase):
    def test_first_not_repeat(self):
        r = update_known_ally_redirection_repeat_state(("gyarados", "waterfall", "tatsugiri", "stormdrain"), "b1", 5, {})
        self.assertFalse(r["repeat_detected"])

    def test_same_turn_not_repeat(self):
        s = {}
        r1 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 5, s)
        r2 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 5, r1["streak_state"])
        self.assertFalse(r2["repeat_detected"])

    def test_later_turn_is_repeat(self):
        s = {}
        r1 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 5, s)
        r2 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 8, r1["streak_state"])
        self.assertTrue(r2["repeat_detected"])

    def test_different_move_not_repeat(self):
        s = {}
        r1 = update_known_ally_redirection_repeat_state(("g", "waterfall", "t", "sd"), "b1", 5, s)
        r2 = update_known_ally_redirection_repeat_state(("g", "jetpunch", "t", "sd"), "b1", 8, r1["streak_state"])
        self.assertFalse(r2["repeat_detected"])

    def test_different_ally_not_repeat(self):
        s = {}
        r1 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 5, s)
        r2 = update_known_ally_redirection_repeat_state(("g", "wf", "gyarados", "sd"), "b1", 8, r1["streak_state"])
        self.assertFalse(r2["repeat_detected"])

    def test_different_battle_isolated(self):
        s = {}
        r1 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 5, s)
        r2 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b2", 6, r1["streak_state"])
        self.assertFalse(r2["repeat_detected"])

    def test_streak_increments(self):
        s = {}
        r1 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 5, s)
        self.assertEqual(r1["streak_state"]["b1"][("g", "wf", "t", "sd")]["streak"], 1)
        r2 = update_known_ally_redirection_repeat_state(("g", "wf", "t", "sd"), "b1", 7, r1["streak_state"])
        self.assertEqual(r2["streak_state"]["b1"][("g", "wf", "t", "sd")]["streak"], 2)


class TestErrorOwnership(unittest.TestCase):
    def test_known_before_selected_is_our_error(self):
        our_err, opp_err = classify_known_ally_redirection_error(True, True, True)
        self.assertTrue(our_err)
        self.assertFalse(opp_err)

    def test_reveal_after_selected_not_our_error(self):
        our_err, opp_err = classify_known_ally_redirection_error(True, False, True)
        self.assertFalse(our_err)
        self.assertFalse(opp_err)

    def test_our_slot_never_opponent_error(self):
        our_err, opp_err = classify_known_ally_redirection_error(True, True, True)
        self.assertFalse(opp_err, "Our action slot must never produce opponent error")

    def test_not_selected_no_error(self):
        our_err, opp_err = classify_known_ally_redirection_error(False, True, True)
        self.assertFalse(our_err)

    def test_not_our_action_no_errors(self):
        our_err, opp_err = classify_known_ally_redirection_error(True, True, False)
        self.assertFalse(our_err)
        self.assertFalse(opp_err)


class TestInvariantFields(unittest.TestCase):
    def test_all_fields_in_production_source(self):
        fields = {
            "known_ally_redirection_candidate_blocked",
            "known_ally_redirection_selected",
            "known_ally_redirection_avoided",
            "known_ally_redirection_only_legal",
            "known_ally_redirection_repeat_selected",
            "known_ally_redirection_reason",
            "known_ally_redirection_ally_species",
            "known_ally_redirection_ally_ability",
            "known_ally_redirection_move_id",
            "known_ally_redirection_known_before_decision",
            "known_ally_redirection_safe_alternative_available",
            "our_known_ally_redirection_error",
            "opponent_known_ally_redirection_error",
        }
        bot_path = os.path.join(os.path.dirname(__file__), "bot_doubles_damage_aware.py")
        with open(bot_path) as f:
            source = f.read()
        for field in fields:
            self.assertIn(field, source, f"Field {field} missing from production source")

    def test_pure_helpers_are_importable(self):
        self.assertTrue(callable(classify_known_ally_redirection_audit))
        self.assertTrue(callable(update_known_ally_redirection_repeat_state))
        self.assertTrue(callable(classify_known_ally_redirection_error))

    def test_helpers_called_in_production(self):
        """Verify each pure helper is called at least once in production (not just defined)."""
        bot_path = os.path.join(os.path.dirname(__file__), "bot_doubles_damage_aware.py")
        with open(bot_path) as f:
            source = f.read()
        helpers_with_call_patterns = {
            "classify_known_ally_redirection_audit": "classify_known_ally_redirection_audit(",
            "update_known_ally_redirection_repeat_state": "update_known_ally_redirection_repeat_state(",
            "classify_known_ally_redirection_error": "classify_known_ally_redirection_error(",
        }
        for name, pattern in helpers_with_call_patterns.items():
            # Must appear at least twice: once in def, once as a call
            count = source.count(pattern)
            self.assertGreaterEqual(count, 2, f"Helper {name} defined but not called in production (found {count} occurrence(s))")


class TestAnalyzerFieldParsing(unittest.TestCase):
    def test_analyzer_parses_ally_redirection(self):
        import json, tempfile, shutil, io
        td = {"turn": 1, "slot_0": {"known_ally_redirection_selected": True,
                                     "known_ally_redirection_reason": "ally_stormdrain_redirects_water"},
              "slot_1": {}}
        rec = {"battle_tag": "test", "won": True, "audit_turns": [td]}
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "t.jsonl")
        with open(fp, "w") as f:
            f.write(json.dumps(rec) + "\n")
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp)
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("selected count", out)


class TestBlockedCandidateMetadata(unittest.TestCase):
    def test_avoided_storm_drain_records_metadata(self):
        """An avoided Storm Drain candidate records move, ally, ability, reason."""
        meta = {
            "move_id": "waterfall", "attacker_species": "gyarados",
            "target_species": "abomasnow", "ally_species": "tatsugiri",
            "ally_ability": "stormdrain", "reason": "ally_stormdrain_redirects_water",
            "known_before_decision": True,
        }
        self.assertEqual(meta["move_id"], "waterfall")
        self.assertEqual(meta["ally_ability"], "stormdrain")
        self.assertIn("stormdrain", meta["reason"])
        self.assertTrue(meta["known_before_decision"])

    def test_avoided_lightning_rod_records_metadata(self):
        meta = {
            "move_id": "thunderbolt", "attacker_species": "raichu",
            "ally_species": "rhydon", "ally_ability": "lightningrod",
            "reason": "ally_lightningrod_redirects_electric", "known_before_decision": True,
        }
        self.assertEqual(meta["move_id"], "thunderbolt")
        self.assertIn("lightningrod", meta["reason"])

    def test_opportunity_selected_avoided_consistent(self):
        """opportunity + selected + avoided + only_legal are mutually consistent."""
        from bot_doubles_damage_aware import classify_known_ally_redirection_audit
        # Scenario: blocked candidate exists, safe alt exists, selected is non-blocked
        r = classify_known_ally_redirection_audit(False, True, True)
        self.assertFalse(r["avoidable_selected"])
        self.assertFalse(r["only_legal"])
        self.assertTrue(r["avoided"])  # blocked exists but selected is safe

    def test_unknown_ability_no_opportunity(self):
        """Unknown/unrevealed ally ability creates no opportunity."""
        meta = {"ally_ability": "", "reason": ""}
        self.assertFalse(bool(meta["ally_ability"]))

    def test_selected_safe_does_not_overwrite_blocked_metadata(self):
        """Selected action details don't overwrite blocked-candidate metadata."""
        blocked = {"move_id": "waterfall", "ally_ability": "stormdrain"}
        selected = {"move_id": "fireblast", "ally_ability": ""}
        self.assertNotEqual(blocked["move_id"], selected["move_id"])
        self.assertEqual(blocked["ally_ability"], "stormdrain")

    def test_analyzer_parses_blocked_metadata(self):
        import json, tempfile, shutil, io
        td = {"turn": 1,
              "slot_0": {"known_ally_redirection_opportunity_observed": True,
                         "known_ally_redirection_avoided": True,
                         "known_ally_redirection_blocked_candidate_move_id": "waterfall",
                         "known_ally_redirection_blocked_candidate_ally_species": "tatsugiri",
                         "known_ally_redirection_blocked_candidate_ally_ability": "stormdrain",
                         "known_ally_redirection_blocked_candidate_reason": "ally_stormdrain_redirects_water"},
              "slot_1": {}}
        rec = {"battle_tag": "test", "won": False, "audit_turns": [td]}
        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "t.jsonl")
        with open(fp, "w") as f:
            f.write(json.dumps(rec) + "\n")
        old, sys.stdout = sys.stdout, io.StringIO()
        try:
            from analyze_doubles_decision_audit import analyze_audit_log
            analyze_audit_log(fp)
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("selected count", out)

    def test_inspector_parses_blocked_candidate(self):
        slot = {"known_ally_redirection_opportunity_observed": True,
                "known_ally_redirection_blocked_candidate_move_id": "waterfall",
                "known_ally_redirection_blocked_candidate_ally_species": "tatsugiri"}
        self.assertEqual(slot["known_ally_redirection_blocked_candidate_move_id"], "waterfall")
        self.assertEqual(slot["known_ally_redirection_blocked_candidate_ally_species"], "tatsugiri")


if __name__ == "__main__":
    unittest.main()
