"""Phase PROTECT-1 — Tests for the Protect usage
diagnostic. Tiny temp JSONL fixtures, no large logs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from diagnose_protect_usage import (  # noqa: E402
    _expected_faint_slot,
    _hp_bucket,
    _is_move_key,
    _is_protect_key,
    _is_switch_key,
    _per_slot_protect_legal,
    _per_slot_protect_selected,
    _per_slot_move_attack,
    _per_slot_switch,
    _protect_floor_debug_slot,
    _protect_score_slot,
    _best_attack_score_slot,
    _score_diff_slot,
    _speed_priority_threat_slot,
    _switch_cf_delta_slot,
    PROTECT_LIKE,
    collect_audit,
    main,
)


def _make_turn(
    turn_n: int = 1,
    legal0=None,
    legal1=None,
    sel0=None,
    sel1=None,
    ef=None,
    sp=None,
    scf_slot0=None,
    scf_slot1=None,
    state=None,
):
    t = {
        "turn": turn_n,
    }
    if legal0 is not None:
        t["v4a_legal_action_keys_slot0"] = legal0
    if legal1 is not None:
        t["v4a_legal_action_keys_slot1"] = legal1
    sel = []
    if sel0 is not None:
        sel.append(sel0)
    if sel1 is not None:
        sel.append(sel1)
    if sel:
        t["v4a_selected_joint_key"] = sel
    if ef is not None:
        t["expected_to_faint_before_moving"] = ef
    if sp is not None:
        t["speed_priority_threatened"] = sp
    scf = {}
    if scf_slot0 is not None:
        scf["slot0"] = scf_slot0
    if scf_slot1 is not None:
        scf["slot1"] = scf_slot1
    if scf:
        t["switch_counterfactual"] = scf
    if state is not None:
        t["state_snapshot"] = state
    return t


def _make_row(battle_tag: str = "b1", won=True, turns=None):
    if turns is None:
        turns = []
    return {
        "battle_tag": battle_tag,
        "won": won,
        "audit_turns": turns,
    }


class TestProtectDetection(unittest.TestCase):
    def test_is_protect_key(self):
        self.assertTrue(
            _is_protect_key(["move", "protect", 0, ""])
        )
        self.assertTrue(
            _is_protect_key(["move", "Detect", 0, ""])
        )
        self.assertTrue(
            _is_protect_key(["move", "kingsshield", 0, ""])
        )
        self.assertFalse(
            _is_protect_key(["move", "tackle", 0, ""])
        )
        self.assertFalse(_is_protect_key(None))
        self.assertFalse(_is_protect_key("protect"))
        self.assertFalse(_is_protect_key(["move"]))

    def test_is_move_key(self):
        self.assertTrue(_is_move_key(["move", "tackle", 0, ""]))
        self.assertTrue(_is_move_key(["move", "protect", 0, ""]))
        self.assertFalse(_is_switch_key(["move", "tackle", 0, ""]))

    def test_is_switch_key(self):
        self.assertTrue(
            _is_switch_key(["switch", "garchomp", 0, ""])
        )
        self.assertFalse(
            _is_switch_key(["move", "garchomp", 0, ""])
        )

    def test_hp_bucket(self):
        self.assertEqual(_hp_bucket(0.1), "<25%")
        self.assertEqual(_hp_bucket(0.3), "25-50%")
        self.assertEqual(_hp_bucket(0.6), "50-75%")
        self.assertEqual(_hp_bucket(0.9), "75-100%")
        self.assertEqual(_hp_bucket(None), "unknown")
        self.assertEqual(_hp_bucket(1.5), "unknown")

    def test_protect_like_set(self):
        # Ensure the allowlist contains the canonical moves.
        for m in (
            "protect", "detect", "kingsshield",
            "spikyshield", "banefulbunker", "silktrap",
        ):
            self.assertIn(m, PROTECT_LIKE)


class TestPerSlotDetection(unittest.TestCase):
    def test_per_slot_protect_legal(self):
        t = _make_turn(
            legal0=[
                ["move", "tackle", 0, ""],
                ["move", "protect", 0, ""],
            ],
            legal1=[["move", "fakeout", 1, ""]],
        )
        self.assertTrue(_per_slot_protect_legal(t, 0))
        self.assertFalse(_per_slot_protect_legal(t, 1))

    def test_per_slot_protect_selected(self):
        t = _make_turn(
            sel0=["move", "protect", 0, ""],
            sel1=["move", "fakeout", 1, ""],
        )
        self.assertTrue(_per_slot_protect_selected(t, 0))
        self.assertFalse(_per_slot_protect_selected(t, 1))

    def test_per_slot_move_attack(self):
        # Move-attack = move kind, not protect, not switch.
        t = _make_turn(
            sel0=["move", "tackle", 0, ""],
            sel1=["move", "protect", 0, ""],
        )
        self.assertTrue(_per_slot_move_attack(t, 0))
        self.assertFalse(_per_slot_move_attack(t, 1))

    def test_per_slot_switch(self):
        t = _make_turn(
            sel0=["switch", "garchomp", 0, ""],
            sel1=["move", "protect", 0, ""],
        )
        self.assertTrue(_per_slot_switch(t, 0))
        self.assertFalse(_per_slot_switch(t, 1))


class TestFieldReaders(unittest.TestCase):
    def test_expected_faint_slot(self):
        t = _make_turn(ef=[True, False])
        self.assertEqual(_expected_faint_slot(t, 0), True)
        self.assertEqual(_expected_faint_slot(t, 1), False)
        t = _make_turn()  # no ef
        self.assertIsNone(_expected_faint_slot(t, 0))
        t = _make_turn(ef=[None, None])
        self.assertIsNone(_expected_faint_slot(t, 0))

    def test_speed_priority_threat_slot(self):
        t = _make_turn(sp=[True, False])
        self.assertEqual(
            _speed_priority_threat_slot(t, 0), True
        )
        self.assertEqual(
            _speed_priority_threat_slot(t, 1), False
        )

    def test_switch_cf_delta_slot(self):
        t = _make_turn(
            scf_slot0={
                "switch_vs_non_switch_delta": 50.0
            }
        )
        self.assertEqual(_switch_cf_delta_slot(t, 0), 50.0)
        self.assertIsNone(_switch_cf_delta_slot(t, 1))
        t = _make_turn()  # no scf
        self.assertIsNone(_switch_cf_delta_slot(t, 0))


class TestCollectAudit(unittest.TestCase):
    def test_collect_basic_counts(self):
        turn = _make_turn(
            legal0=[
                ["move", "tackle", 0, ""],
                ["move", "protect", 0, ""],
            ],
            legal1=[["move", "fakeout", 1, ""]],
            sel0=["move", "tackle", 0, ""],
            sel1=["move", "fakeout", 1, ""],
            ef=[False, False],
            sp=[False, False],
            state={
                "our_active_hp_fraction": [0.8, 0.6],
            },
        )
        row = _make_row(battle_tag="b1", won=True, turns=[turn])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps(row) + "\n")
            data = collect_audit([path])
        self.assertEqual(data["turns"], 1)
        self.assertEqual(data["v4a_coverage"], 1)
        self.assertEqual(data["speed_priority_coverage"], 1)
        self.assertEqual(data["expected_faint_coverage"], 1)
        self.assertEqual(
            data["protect_legal_by_slot"]["slot0"], 1
        )
        self.assertEqual(
            data["protect_legal_by_slot"]["slot1"], 0
        )
        self.assertEqual(
            data["protect_legal_but_not_selected_by_slot"][
                "slot0"
            ],
            1,
        )
        self.assertEqual(
            data["protect_selected_by_slot"]["slot0"], 0
        )
        self.assertEqual(
            data["move_attack_selected_by_slot"]["slot0"], 1
        )
        # ef=False + Protect legal + attack chosen
        self.assertEqual(
            data["exp_faint_false_protect_legal_attack_chosen"],
            1,
        )
        # ef=False + Protect legal + Protect chosen = 0
        self.assertEqual(
            data["exp_faint_false_protect_legal_protect_chosen"],
            0,
        )

    def test_collect_attack_through(self):
        turn = _make_turn(
            legal0=[
                ["move", "tackle", 0, ""],
                ["move", "protect", 0, ""],
            ],
            sel0=["move", "tackle", 0, ""],
            ef=[True, False],
            sp=[True, False],
            state={"our_active_hp_fraction": [0.2, 0.5]},
        )
        row = _make_row(won=False, turns=[turn])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps(row) + "\n")
            data = collect_audit([path])
        # ef=True + Protect legal + attack chosen = 1
        self.assertEqual(
            data["exp_faint_true_protect_legal_attack_chosen"],
            1,
        )
        # Won/lost attack-through
        self.assertEqual(data["lost_attack_through"], 1)
        self.assertEqual(data["won_attack_through"], 0)
        # HP bucket <25% for attack selected
        self.assertEqual(
            data["move_attack_selected_hp_bucket"]["<25%"], 1
        )

    def test_collect_protect_chosen(self):
        turn = _make_turn(
            legal0=[["move", "protect", 0, ""]],
            sel0=["move", "protect", 0, ""],
            ef=[True, False],
            sp=[True, False],
            state={"our_active_hp_fraction": [0.4, 0.5]},
        )
        row = _make_row(won=True, turns=[turn])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps(row) + "\n")
            data = collect_audit([path])
        self.assertEqual(
            data["protect_selected_by_slot"]["slot0"], 1
        )
        self.assertEqual(
            data["exp_faint_true_protect_legal_protect_chosen"],
            1,
        )
        self.assertEqual(data["won_protect_chosen"], 1)
        self.assertEqual(data["sp_threat_true_protect_chosen"], 1)
        # HP 0.4 is 25-50%
        self.assertEqual(
            data["protect_selected_hp_bucket"]["25-50%"], 1
        )


class TestEndToEnd(unittest.TestCase):
    def test_main_creates_outputs(self):
        turn = _make_turn(
            legal0=[
                ["move", "tackle", 0, ""],
                ["move", "protect", 0, ""],
            ],
            sel0=["move", "tackle", 0, ""],
            ef=[True, False],
        )
        row = _make_row(turns=[turn])
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "audit.jsonl")
            with open(inp, "w") as f:
                f.write(json.dumps(row) + "\n")
            md = os.path.join(tmp, "out.md")
            js = os.path.join(tmp, "out.json")
            rc = main([
                "--input", inp,
                "--output-md", md,
                "--output-json", js,
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(md))
            self.assertTrue(os.path.exists(js))

    def test_main_missing_input_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main([
                "--input",
                os.path.join(tmp, "missing.jsonl"),
                "--output-md",
                os.path.join(tmp, "out.md"),
                "--output-json",
                os.path.join(tmp, "out.json"),
            ])
            self.assertEqual(rc, 2)


class TestFixtureAdequate(unittest.TestCase):
    def test_adequate_synthetic_yields_decision(self):
        """A multi-turn synthetic dataset should yield
        all key counts > 0 so the report is meaningful.
        """
        rows = []
        # 5 turns: 2 protect chosen, 3 attack-through
        for i in range(5):
            turn = _make_turn(
                turn_n=i + 1,
                legal0=[
                    ["move", "tackle", 0, ""],
                    ["move", "protect", 0, ""],
                ],
                sel0=(
                    ["move", "protect", 0, ""]
                    if i < 2
                    else ["move", "tackle", 0, ""]
                ),
                ef=[True, False],
                sp=[True, False],
                state={
                    "our_active_hp_fraction": [0.3, 0.6]
                },
            )
            rows.append(_make_row(turns=[turn]))
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "audit.jsonl")
            with open(inp, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            data = collect_audit([inp])
        self.assertEqual(data["turns"], 5)
        self.assertEqual(
            data["protect_selected_total"], 2
        )
        self.assertEqual(
            data["exp_faint_true_protect_legal_attack_chosen"],
            3,
        )
        # Top attack-through list non-empty.
        self.assertGreater(
            len(data["top_attack_through"]), 0
        )


class TestProtectFloorDebugPath(unittest.TestCase):
    """Phase PROTECT-2: prove the diagnostic reads the
    correct nested field path for
    speed_priority_protect_floor_debug.
    """

    def test_protect_floor_debug_slot_returns_nested_dict(self):
        """The diagnostic must read
        speed_priority_protect_floor_debug.slot{idx},
        not a top-level `protect_floor_applied` field.
        """
        t = {
            "speed_priority_protect_floor_debug": {
                "slot0": {
                    "floor_applied": True,
                    "floor_value": 240.0,
                    "protect_score_before_floor": 0.0,
                    "protect_score_after_floor": 240.0,
                    "expected_faint": True,
                    "action_count": 2,
                    "selected_action_key": "move|protect|0",
                    "protect_like_keys": ["move|protect|0"],
                },
                "slot1": {
                    "floor_applied": False,
                    "floor_value": 240.0,
                },
            }
        }
        s0 = _protect_floor_debug_slot(t, 0)
        self.assertTrue(s0.get("floor_applied"))
        self.assertEqual(s0.get("floor_value"), 240.0)
        s1 = _protect_floor_debug_slot(t, 1)
        self.assertFalse(s1.get("floor_applied"))

    def test_protect_floor_debug_slot_returns_empty_when_missing(
        self,
    ):
        t = {}
        self.assertEqual(_protect_floor_debug_slot(t, 0), {})
        t = {"speed_priority_protect_floor_debug": {}}
        self.assertEqual(_protect_floor_debug_slot(t, 0), {})

    def test_collect_counts_floor_applied(self):
        """When the BEHAVIOR-18 audit has
        speed_priority_protect_floor_debug with
        floor_applied=True, the collector must count
        it under protect_floor_applied_per_slot.
        """
        turn = _make_turn(
            turn_n=1,
            legal0=[
                ["move", "tackle", 0, ""],
                ["move", "protect", 0, ""],
            ],
            sel0=["move", "protect", 0, ""],
            ef=[True, False],
            sp=[True, False],
        )
        # Inject the correct nested field.
        turn["speed_priority_protect_floor_debug"] = {
            "slot0": {
                "floor_applied": True,
                "floor_value": 240.0,
                "expected_faint": True,
                "protect_like_keys": ["move|protect|0"],
            },
            "slot1": {},
        }
        row = _make_row(turns=[turn])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps(row) + "\n")
            data = collect_audit([path])
        # Floor present + applied for slot0.
        self.assertEqual(
            data["protect_floor_present_per_slot"]["slot0"],
            1,
        )
        self.assertEqual(
            data["protect_floor_applied_per_slot"]["slot0"],
            1,
        )
        # Floor applied + Protect chosen.
        self.assertEqual(
            data[
                "floor_applied_protect_chosen_per_slot"
            ]["slot0"],
            1,
        )
        # ef=True + floor applied.
        self.assertEqual(
            data["floor_applied_ef_true_per_slot"]["slot0"],
            1,
        )
        # Floor NOT applied for slot1.
        self.assertEqual(
            data["protect_floor_present_per_slot"]["slot1"],
            0,
        )

    def test_protect_score_slot_and_best_attack_score(self):
        t = {
            "speed_priority_protect_score_slot0": 240.0,
            "speed_priority_best_attack_score_slot0": 350.0,
        }
        self.assertEqual(_protect_score_slot(t, 0), 240.0)
        self.assertEqual(_best_attack_score_slot(t, 0), 350.0)
        # Missing fields return None.
        self.assertIsNone(_protect_score_slot({}, 0))
        self.assertIsNone(_best_attack_score_slot({}, 0))

    def test_score_diff_slot(self):
        t = {
            "speed_priority_score_diff_slot0": -1139.16,
        }
        self.assertEqual(_score_diff_slot(t, 0), -1139.16)
        self.assertIsNone(_score_diff_slot({}, 0))


class TestRealArtifactFloorCounts(unittest.TestCase):
    """Phase PROTECT-2: prove the diagnostic counts
    floor_applied > 0 against the real BEHAVIOR-17/18
    audit artifacts (where the field is present).
    This is the smoke that PROTECT-1's "0 applied"
    was a wrong-field bug, not a real bug.
    """

    BEHAVIOR18_TREATMENT = (
        "logs/vgc2026_phaseBEHAVIOR18_candidate_independent"
        "_expected_faint_smoke5_v1_treatment_audit.jsonl"
    )
    BEHAVIOR17_TREATMENT = (
        "logs/vgc2026_phaseBEHAVIOR17_protect_floor_path"
        "_audit_smoke5_v1_treatment_audit.jsonl"
    )

    def test_real_floor_counts_nonzero(self):
        """BEHAVIOR-18 audits must report
        floor_applied > 0 when the correct field path
        is read. (BEHAVIOR-17 audits predate the fix
        and may have floor_applied = 0; that is the
        expected evolution of the path.)
        """
        if not os.path.exists(self.BEHAVIOR18_TREATMENT):
            self.skipTest("BEHAVIOR-18 audit not present")
        data = collect_audit([self.BEHAVIOR18_TREATMENT])
        total = sum(
            data["protect_floor_applied_per_slot"].values()
        )
        self.assertGreater(
            total, 0,
            f"floor_applied should be > 0 for "
            f"BEHAVIOR-18 audit; "
            f"got {data['protect_floor_applied_per_slot']}"
        )


if __name__ == "__main__":
    unittest.main()
