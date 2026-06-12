"""Phase 6.3.7n.3 — Targeted Qualification Unit Tests (integrity-fixed)."""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(__file__))
import poke_env_test_cleanup  # noqa

from poke_env.player.player import ConstantTeambuilder
from poke_env.battle.move import Move
from bot_doubles_damage_aware import (
    find_protocol_ability_reveal_turn, classify_dynamic_type_absorb_candidates,
    DoublesDamageAwareConfig, _get_pokemon_by_ident,
)


class TestFixedTeams(unittest.TestCase):
    def test_our_team_parses(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import OUR_TEAM
        packed = ConstantTeambuilder(OUR_TEAM).yield_team()
        self.assertIn("morpeko", packed.lower())

    def test_opp_team_parses(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import OPP_TEAM
        packed = ConstantTeambuilder(OPP_TEAM).yield_team()
        self.assertIn("lanturn", packed.lower())

    def test_default_config(self):
        c = DoublesDamageAwareConfig()
        self.assertTrue(c.enable_ability_hard_safety_only)
        self.assertFalse(c.ability_hard_safety_avoid_absorb)
        self.assertFalse(c.enable_ability_awareness)


class TestRevealHelper(unittest.TestCase):
    def _battle(self, events, turn=5, get_pokemon_fn=None):
        b = MagicMock(); b.turn = turn; b._replay_data = events
        if get_pokemon_fn:
            b.get_pokemon = get_pokemon_fn
        return b

    def test_exact_identity_ability(self):
        target = MagicMock(); target._ident = "p2a"
        b = self._battle([["","turn","3"],["","-ability","p2: Lanturn","Volt Absorb"]],
                         get_pokemon_fn=lambda ident: target if "p2" in str(ident) else None)
        self.assertEqual(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"), 3)

    def test_wrong_target_ability_rejected(self):
        t1 = MagicMock(); t1._ident = "p2a"
        t2 = MagicMock(); t2._ident = "p2b"
        b = self._battle([["","turn","3"],["","-ability","p2: Lanturn","Volt Absorb"]],
                         get_pokemon_fn=lambda ident: t2 if "p2" in str(ident) else None)
        self.assertIsNone(find_protocol_ability_reveal_turn(b, t1, "Volt Absorb"))

    def test_same_species_two_slots(self):
        t_slot0 = MagicMock(); t_slot0._ident = "slot0"
        t_slot1 = MagicMock(); t_slot1._ident = "slot1"
        b = self._battle([["","turn","3"],["","-ability","p2: Lanturn","Volt Absorb"]],
                         get_pokemon_fn=lambda ident: t_slot1 if "p2" in str(ident) else None)
        self.assertIsNone(find_protocol_ability_reveal_turn(b, t_slot0, "Volt Absorb"))

    def test_future_event_blocked(self):
        target = MagicMock(); target._ident = "p2"
        b = self._battle([["","turn","3"],["","-ability","p2a: Lanturn","Volt Absorb"]], turn=2,
                         get_pokemon_fn=lambda ident: target if "p2" in str(ident) else None)
        self.assertIsNone(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"))

    def test_earlier_reveal_visible_later(self):
        target = MagicMock(); target._ident = "p2"
        b = self._battle([["","turn","3"],["","-ability","p2a: Lanturn","Volt Absorb"]], turn=5,
                         get_pokemon_fn=lambda ident: target if "p2" in str(ident) else None)
        self.assertEqual(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"), 3)

    def test_no_reveal_returns_none(self):
        b = self._battle([["","turn","1"]])
        self.assertIsNone(find_protocol_ability_reveal_turn(b, MagicMock(), "Volt Absorb"))

    def test_from_ability_exact_owner_and_name(self):
        target = MagicMock()
        other = MagicMock()
        b = self._battle(
            [["", "turn", "3"],
             ["", "-heal", "p2a: Lanturn", "100/100",
              "[from] ability: Volt Absorb", "[of] p2a: Lanturn"]],
            get_pokemon_fn=lambda ident: target if "p2a" in str(ident) else other,
        )
        self.assertEqual(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"), 3)
        self.assertIsNone(find_protocol_ability_reveal_turn(b, other, "Volt Absorb"))

    def test_from_ability_non_equal_name_rejected(self):
        target = MagicMock()
        b = self._battle(
            [["", "turn", "3"],
             ["", "-heal", "p2a: Lanturn", "100/100",
              "[from] ability: Super Volt Absorb", "[of] p2a: Lanturn"]],
            get_pokemon_fn=lambda ident: target,
        )
        self.assertIsNone(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"))

    def test_supported_subject_fallback(self):
        target = MagicMock()
        b = self._battle(
            [["", "turn", "3"],
             ["", "-heal", "p2a: Lanturn", "100/100",
              "[from] ability: Volt Absorb"]],
            get_pokemon_fn=lambda ident: target,
        )
        self.assertEqual(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"), 3)

    def test_unsupported_subject_fallback_rejected(self):
        target = MagicMock()
        b = self._battle(
            [["", "turn", "3"],
             ["", "-message", "p2a: Lanturn", "[from] ability: Volt Absorb"]],
            get_pokemon_fn=lambda ident: target,
        )
        self.assertIsNone(find_protocol_ability_reveal_turn(b, target, "Volt Absorb"))


class TestKnownBeforeSemantics(unittest.TestCase):
    def _make_move(self):
        m = MagicMock(spec=Move)
        type(m).id = PropertyMock(return_value="aurawheel")
        type(m).base_power = PropertyMock(return_value=80)
        return m

    def _make_order(self, move, tgt=1):
        class O:
            pass
        o = O()
        o.order = move
        o.move_target = tgt
        return o

    def _make_target(self, species):
        t = MagicMock(); t.species = species; t.fainted = False; return t

    def test_singleton_not_counted_as_known_before(self):
        move = self._make_move(); c = self._make_order(move)
        target = self._make_target("Lanturn")
        attacker = MagicMock(); attacker.species = "morpeko"; attacker.base_species = "morpeko"
        b = MagicMock(); b.turn = 5; b.battle_tag = "test"
        b._replay_data = [["","turn","3"],["","-ability","p2: Lanturn","Volt Absorb"]]
        b.get_pokemon = lambda ident, **kw: target if "p2" in str(ident) else None
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_known_ability", return_value={
                "ability":"voltabsorb","source":"singleton_deduced","is_deterministic":True}):
                with patch("bot_doubles_damage_aware.resolve_effective_move_type", return_value={
                    "declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                    "dynamic_applied":True,"observed_form":"morpeko","source":"static"}):
                    r = classify_dynamic_type_absorb_candidates(
                        [c], c, attacker, [target, None], b, DoublesDamageAwareConfig(), {id(c):100})
        row = r["dynamic_candidate_target_table"][0]
        self.assertEqual(row["target_known_ability_source"], "singleton_deduced")
        self.assertFalse(row["target_ability_known_before_decision"])

    def test_protocol_revealed_with_future_event_not_known_before(self):
        move = self._make_move(); c = self._make_order(move)
        target = self._make_target("Lanturn")
        attacker = MagicMock(); attacker.species = "morpeko"; attacker.base_species = "morpeko"
        b = MagicMock(); b.turn = 3; b.battle_tag = "test"
        b._replay_data = [["","turn","5"],["","-ability","p2: Lanturn","Volt Absorb"]]
        b.get_pokemon = lambda ident, **kw: target if "p2" in str(ident) else None
        with patch("bot_doubles_damage_aware.get_known_ability", return_value="voltabsorb"):
            with patch("bot_doubles_damage_aware.resolve_known_ability", return_value={
                "ability":"voltabsorb","source":"protocol_revealed","is_deterministic":True}):
                with patch("bot_doubles_damage_aware.resolve_effective_move_type", return_value={
                    "declared_type":"ELECTRIC","effective_type":"ELECTRIC",
                    "dynamic_applied":True,"observed_form":"morpeko","source":"static"}):
                    r = classify_dynamic_type_absorb_candidates(
                        [c], c, attacker, [target, None], b, DoublesDamageAwareConfig(), {id(c):100})
        row = r["dynamic_candidate_target_table"][0]
        self.assertFalse(row["target_ability_known_before_decision"])


class TestExtractorGates(unittest.TestCase):
    def _write(self, fp, records):
        with open(fp, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def _row(self, form, eff, **kw):
        return dict({"move_id":"aurawheel","form":form,"effective_type":eff,
                      "target_known_ability":kw.pop("target_known_ability","voltabsorb"),
                      "target_known_ability_source":kw.pop("ab_src","protocol_revealed"),
                      "target_ability_known_before_decision":kw.pop("known_before",True),
                      "target_ability_reveal_turn":kw.pop("reveal",4),
                      "decision_turn":kw.pop("dturn",6),
                      "ability_blocked":kw.pop("blocked",False),
                      "selected":kw.pop("sel",False),
                      "target_species":kw.pop("species","lanturn"),
                      "target_identity":kw.pop("target_identity","p2: Lanturn"),
                      "source":"static","target_position":1}, **kw)

    def test_setup_action_captured(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"selected_joint_order":"/choose move aurawheel|move protect",
             "slot_0":{"dynamic_type_absorb_candidate_target_table":[
                 self._row("morpeko","ELECTRIC",target_known_ability="",ab_src="",known_before=False,reveal=None,dturn=4,sel=True,blocked=False,species="lanturn")]}},
            {"turn":6,"selected_joint_order":"/choose move protect|move protect",
             "slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                        "dynamic_type_absorb_avoided":True,
                        "selected_action_kind":"move",
                        "selected_action_move_id":"protect",
                        "selected_action_target_position":0,
                        "dynamic_type_absorb_candidate_target_table":[
                 self._row("morpeko","ELECTRIC",dturn=6,blocked=True,sel=False)]}},
            {"turn":8,"selected_joint_order":"/choose move aurawheel|move protect",
             "slot_0":{"selected_action_kind":"move",
                        "selected_action_move_id":"aurawheel",
                        "selected_action_target_position":1,
                        "dynamic_type_absorb_candidate_target_table":[
                 self._row("morpekohangry","DARK",dturn=8,blocked=False,sel=True)]}},
            {"turn":10,"selected_joint_order":"/choose move protect|move protect",
             "slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                        "dynamic_type_absorb_avoided":True,
                        "selected_action_kind":"move",
                        "selected_action_move_id":"protect",
                        "selected_action_target_position":0,
                        "dynamic_type_absorb_candidate_target_table":[
                 self._row("morpeko","ELECTRIC",dturn=10,blocked=True,sel=False)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertTrue(ev["bt1"]["setup_valid"], msg=ev["bt1"]["failure_reason"])
        self.assertEqual(ev["bt1"]["setup_reveal_action_turn"], 4)
        self.assertEqual(ev["bt1"]["setup_reveal_action_move"], "aurawheel")
        self.assertTrue(ev["bt1"]["setup_reveal_was_unknown_before"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_no_setup_action_fails(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":6,"selected_joint_order":"/choose move protect|move protect",
             "slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                        "dynamic_type_absorb_avoided":True,
                        "dynamic_type_absorb_candidate_target_table":[
                 self._row("morpeko","ELECTRIC",dturn=6,blocked=True,sel=False)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertFalse(ev["bt1"]["setup_valid"])
        self.assertIn("no unknown-before", ev["bt1"]["failure_reason"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_setup_not_selected_fails(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",ab_src="",known_before=False,reveal=None,dturn=4,sel=False)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertFalse(ev["bt1"]["setup_valid"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_setup_already_knew_fails(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=4,sel=True,blocked=False)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertFalse(ev["bt1"]["setup_valid"])
        self.assertIn("no unknown-before", ev["bt1"]["failure_reason"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_decision_turn_mismatch_discards(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",target_known_ability="",ab_src="",
                          known_before=False,reveal=None,dturn=3,sel=True)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertIn("decision_turn mismatch", ev["bt1"]["failure_reason"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_same_turn_hangry_fails(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",ab_src="",known_before=False,reveal=None,dturn=4,sel=True)]}},
            {"turn":6,"slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                                 "dynamic_type_absorb_avoided":True,
                                 "dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=6,blocked=True,sel=False)]}},
            {"turn":6,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpekohangry","DARK",dturn=6,blocked=False,sel=True)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertFalse(ev["bt1"]["setup_valid"])
        self.assertIn("missing Hangry after Full Belly", ev["bt1"]["failure_reason"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_no_safe_alternative_fails(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",target_known_ability="",ab_src="",known_before=False,reveal=None,dturn=4,sel=True,blocked=False,species="lanturn")]}},
            {"turn":6,"slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                                 "dynamic_type_absorb_avoided":True,
                                 "selected_action_kind":"move",
                                 "selected_action_move_id":"protect",
                                 "selected_action_target_position":0,
                                 "dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=6,blocked=True,sel=False)]}},
            {"turn":8,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpekohangry","DARK",dturn=8,blocked=False,sel=True)]}},
            {"turn":10,"slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                                  "dynamic_type_absorb_avoided":False,
                                  "selected_action_kind":"move",
                                  "selected_action_move_id":"protect",
                                  "selected_action_target_position":0,
                                  "dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=10,blocked=True,sel=False)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)
        self.assertIn("reverse Full Belly avoided flag not set", ev["bt1"]["failure_reason"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_old_phase637n_artifacts_discard(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        old = "logs/dynamic_type_targeted_phase637n.jsonl"
        if not os.path.exists(old):
            self.skipTest("old artifacts not found")
        for bt, e in _extract_evidence(old).items():
            self.assertFalse(e["setup_valid"], f"{bt} should be DISCARD")

    def test_target_identity_change_discards(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",target_known_ability="",ab_src="",
                          known_before=False,reveal=None,dturn=4,sel=True,
                          target_identity="p2: Lanturn-A")]}},
            {"turn":6,"slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                                 "dynamic_type_absorb_avoided":True,
                                 "selected_action_kind":"move",
                                 "selected_action_move_id":"protect",
                                 "selected_action_target_position":0,
                                 "dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=6,blocked=True,sel=False,
                          target_identity="p2: Lanturn-B")]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)["bt1"]
        self.assertFalse(ev["setup_valid"])
        self.assertFalse(ev["setup_reveal_was_unknown_before"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_setup_uses_candidate_on_actual_reveal_turn(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _extract_evidence
        tmp = tempfile.mkdtemp(); fp = os.path.join(tmp, "t.jsonl")
        unknown = dict(
            target_known_ability="", ab_src="", known_before=False,
            reveal=None, sel=True, blocked=False,
        )
        rec = {"battle_tag":"bt1","won":True,"audit_turns":[
            {"turn":2,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=2,**unknown)]}},
            {"turn":4,"slot_0":{"dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=4,**unknown)]}},
            {"turn":6,"slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                                 "dynamic_type_absorb_avoided":True,
                                 "selected_action_kind":"move",
                                 "selected_action_move_id":"protect",
                                 "selected_action_target_position":0,
                                 "dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=6,blocked=True,sel=False,reveal=4)]}},
            {"turn":8,"slot_0":{"selected_action_kind":"move",
                                 "selected_action_move_id":"aurawheel",
                                 "selected_action_target_position":1,
                                 "dynamic_type_absorb_candidate_target_table":[
                self._row("morpekohangry","DARK",dturn=8,blocked=False,sel=True,reveal=4)]}},
            {"turn":10,"slot_0":{"dynamic_type_absorb_candidate_blocked":True,
                                  "dynamic_type_absorb_avoided":True,
                                  "selected_action_kind":"move",
                                  "selected_action_move_id":"protect",
                                  "selected_action_target_position":0,
                                  "dynamic_type_absorb_candidate_target_table":[
                self._row("morpeko","ELECTRIC",dturn=10,blocked=True,sel=False,reveal=4)]}},
        ]}
        self._write(fp, [rec])
        ev = _extract_evidence(fp)["bt1"]
        self.assertTrue(ev["setup_valid"], ev["failure_reason"])
        self.assertEqual(ev["setup_reveal_action_turn"], 4)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_not_found_exits_nonzero(self):
        import subprocess
        r = subprocess.run(["./venv/bin/python","bot_doubles_dynamic_move_type_targeted_qualification.py",
                            "--artifact-tag","__nonexistent_artifact__"],
                           capture_output=True,text=True,
                           cwd=os.path.dirname(__file__) or ".",
                           timeout=10)
        self.assertNotEqual(r.returncode, 0)


class TestSlotSafeAction(unittest.TestCase):
    def _blocked_row(self):
        return {"move_id": "aurawheel", "target_position": 1}

    def test_protect_is_safe(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _get_slot_safe_action
        result = _get_slot_safe_action({
            "selected_action_kind": "move",
            "selected_action_move_id": "protect",
            "selected_action_target_position": 0,
        }, self._blocked_row())
        self.assertEqual(result["move_id"], "protect")

    def test_switch_is_safe(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _get_slot_safe_action
        result = _get_slot_safe_action({
            "selected_action_kind": "switch",
            "selected_action_species": "blissey",
        }, self._blocked_row())
        self.assertEqual(result["kind"], "switch")

    def test_other_target_is_safe(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _get_slot_safe_action
        result = _get_slot_safe_action({
            "selected_action_kind": "move",
            "selected_action_move_id": "aurawheel",
            "selected_action_target_position": 2,
        }, self._blocked_row())
        self.assertEqual(result["target_position"], 2)

    def test_same_blocked_target_is_not_safe(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _get_slot_safe_action
        result = _get_slot_safe_action({
            "selected_action_kind": "move",
            "selected_action_move_id": "aurawheel",
            "selected_action_target_position": 1,
        }, self._blocked_row())
        self.assertIsNone(result)

    def test_pass_requires_only_legal(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _get_slot_safe_action
        self.assertIsNone(_get_slot_safe_action({
            "selected_action_kind": "pass",
            "selected_action_only_legal": False,
        }, self._blocked_row()))
        self.assertEqual(_get_slot_safe_action({
            "selected_action_kind": "pass",
            "selected_action_only_legal": True,
        }, self._blocked_row())["kind"], "pass")

    def test_empty_action_is_not_safe(self):
        from bot_doubles_dynamic_move_type_targeted_qualification import _get_slot_safe_action
        self.assertIsNone(_get_slot_safe_action({}, self._blocked_row()))


if __name__ == "__main__":
    unittest.main()
