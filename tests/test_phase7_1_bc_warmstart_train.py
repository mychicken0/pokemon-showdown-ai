"""Phase 7.1 — BC warm-start training script tests.

Fast, no GPU required, no training on real dataset.
"""

import json
import os
import sys
import tempfile
import unittest

import torch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, REPO_ROOT)

from showdown_ai.phase7_1_bc_warmstart_train_local import (
    _FORBIDDEN_KEYS,
    FeatureEncoder,
    _extract_action_label,
    build_label_maps,
    battle_split,
    BCMlp,
)


class TestForbiddenKeys(unittest.TestCase):
    """Label leakage guard: these keys must not appear in features."""

    def test_selected_key_stats_forbidden(self):
        self.assertIn("selected_joint_key", _FORBIDDEN_KEYS)
        self.assertIn("selected_per_slot", _FORBIDDEN_KEYS)
        self.assertIn("won", _FORBIDDEN_KEYS)
        self.assertIn("battle_result", _FORBIDDEN_KEYS)
        self.assertIn("terminal_reward", _FORBIDDEN_KEYS)

    def test_outcome_fields_forbidden(self):
        self.assertIn("turn_delta_hp", _FORBIDDEN_KEYS)
        self.assertIn("faint_caused", _FORBIDDEN_KEYS)
        self.assertIn("faint_suffered", _FORBIDDEN_KEYS)

    def test_future_fields_forbidden(self):
        self.assertIn("discounted_return", _FORBIDDEN_KEYS)
        self.assertIn("delayed_reward_placeholder", _FORBIDDEN_KEYS)
        self.assertIn("final_action_keys", _FORBIDDEN_KEYS)
        self.assertIn("top_5_alternatives", _FORBIDDEN_KEYS)


class TestBattleSplit(unittest.TestCase):
    """Battle-aware split must have zero battle overlap."""

    def make_dummy_rows(self, n_battles=10, rows_per=5):
        rows = []
        for b in range(n_battles):
            for t in range(rows_per):
                rows.append({
                    "battle_tag": f"battle-{b}",
                    "episode_id": f"battle-{b}",
                    "turn_index": t,
                    "state_snapshot": {
                        "our_active_species": ["pikachu"],
                        "opp_active_species": ["eevee"],
                        "our_active_hp_fraction": [1.0],
                        "opp_active_hp_fraction": [0.5],
                        "weather": [],
                        "fields": [],
                        "side_conditions": [],
                    },
                    "total_turns": 10,
                    "legal_action_keys_slot0": [["move", "protect", "0", ""]],
                    "legal_action_keys_slot1": [["move", "tackle", "1", ""]],
                    "selected_joint_key": [["move", "protect", "0", ""], ["move", "tackle", "1", ""]],
                })
        return rows

    def test_no_overlap(self):
        rows = self.make_dummy_rows(10, 5)
        train_idx, val_idx, test_idx, train_b, val_b, test_b = battle_split(
            rows, train_pct=0.7, val_pct=0.15, seed=20260701
        )
        self.assertGreater(len(train_b), 0)
        self.assertGreater(len(val_b), 0)
        self.assertGreater(len(test_b), 0)
        self.assertEqual(len(train_b & val_b), 0,
                         "train/val battle overlap detected")
        self.assertEqual(len(train_b & test_b), 0,
                         "train/test battle overlap detected")
        self.assertEqual(len(val_b & test_b), 0,
                         "val/test battle overlap detected")

    def test_deterministic(self):
        rows = self.make_dummy_rows(10, 5)
        _, _, _, tb1, vb1, teb1 = battle_split(rows, seed=42)
        _, _, _, tb2, vb2, teb2 = battle_split(rows, seed=42)
        _, _, _, tb3, vb3, teb3 = battle_split(rows, seed=99)
        self.assertEqual(tb1, tb2)
        self.assertEqual(vb1, vb2)
        self.assertEqual(teb1, teb2)
        # Different seed must differ
        self.assertTrue(tb1 != tb3 or vb1 != vb3 or teb1 != teb3)


class TestExtractActionLabel(unittest.TestCase):
    def test_move_action(self):
        self.assertEqual(
            _extract_action_label(["move", "tailwind", "0", ""]),
            "move|tailwind|0",
        )

    def test_move_with_target(self):
        self.assertEqual(
            _extract_action_label(["move", "thunderbolt", "1", ""]),
            "move|thunderbolt|1",
        )

    def test_switch_action(self):
        self.assertEqual(
            _extract_action_label(["switch", "charizard", "0", ""]),
            "switch|charizard",
        )

    def test_pass_fallback(self):
        self.assertEqual(_extract_action_label(None), "pass")
        self.assertEqual(_extract_action_label([]), "pass")
        self.assertEqual(_extract_action_label(["pass"]), "pass")


class TestLabelMap(unittest.TestCase):
    def test_label_map_deterministic(self):
        rows = [
            {"selected_joint_key": [["move", "protect", "0", ""], ["move", "tackle", "1", ""]]},
            {"selected_joint_key": [["move", "tailwind", "0", ""], ["move", "protect", "0", ""]]},
        ]
        lm1, _ = build_label_maps(rows)
        lm2, _ = build_label_maps(rows)
        self.assertEqual(lm1, lm2)

    def test_label_map_keys(self):
        rows = [
            {"selected_joint_key": [["move", "helpinghand", "-2", ""], ["move", "protect", "0", ""]]},
        ]
        lm, inv = build_label_maps(rows)
        self.assertIn("move|helpinghand|-2", lm)
        self.assertIn("move|protect|0", lm)


class TestFeatureEncoder(unittest.TestCase):
    def test_feature_dim_stable(self):
        rows = [
            {"battle_tag": "b1", "turn_index": 0, "total_turns": 10,
             "state_snapshot": {"our_active_species": ["pikachu"], "opp_active_species": ["eevee"],
                                "our_active_hp_fraction": [1.0], "opp_active_hp_fraction": [0.5],
                                "weather": ["Rain"], "fields": [], "side_conditions": []},
             "legal_action_keys_slot0": [["move", "protect"]],
             "legal_action_keys_slot1": [["move", "tackle"]],
             "selected_score": 180.0, "unknown_support_move_detected": False,
             "used_species_ability_inference": False, "overkill_penalty_triggered": False,
             "focus_fire_triggered": False, "stale_target_avoided": False},
            {"battle_tag": "b2", "turn_index": 5, "total_turns": 20,
             "state_snapshot": {"our_active_species": ["pikachu"], "opp_active_species": ["eevee"],
                                "our_active_hp_fraction": [0.5], "opp_active_hp_fraction": [1.0],
                                "weather": [], "fields": [], "side_conditions": []},
             "legal_action_keys_slot0": [["move", "flamethrower", "1"]],
             "legal_action_keys_slot1": [["move", "protect"]],
             "selected_score": 50.0, "unknown_support_move_detected": True,
             "used_species_ability_inference": False, "overkill_penalty_triggered": False,
             "focus_fire_triggered": True, "stale_target_avoided": False},
        ]
        enc = FeatureEncoder(rows)
        dim = enc.dim
        self.assertGreater(dim, 10, "Feature dim should be > 10")
        for i, r in enumerate(rows):
            f = enc(r)
            self.assertEqual(len(f), dim,
                             f"Row {i}: feature dim {len(f)} != encoder dim {dim}")

    def test_none_handling(self):
        """HP/species None must not crash encoder."""
        rows = [{
            "battle_tag": "b1", "turn_index": 0, "total_turns": 10,
            "state_snapshot": {
                "our_active_species": [None],
                "opp_active_species": [],
                "our_active_hp_fraction": [None],
                "opp_active_hp_fraction": [],
                "weather": None, "fields": None, "side_conditions": None,
            },
            "legal_action_keys_slot0": [],
            "legal_action_keys_slot1": [],
            "selected_score": None, "unknown_support_move_detected": False,
            "used_species_ability_inference": False, "overkill_penalty_triggered": False,
            "focus_fire_triggered": False, "stale_target_avoided": False,
        }]
        enc = FeatureEncoder(rows)
        enc(rows[0])  # must not crash


class TestModelArchitecture(unittest.TestCase):
    def test_forward_pass_cpu(self):
        import torch
        model = BCMlp(input_dim=100, num_classes=50, hidden=64)
        x = torch.randn(8, 100)
        out = model(x)
        self.assertEqual(out.shape, (8, 50))

    def test_device_cpu(self):
        import torch
        model = BCMlp(100, 50, hidden=64)
        x = torch.randn(4, 100)
        out = model(x)
        self.assertEqual(out.shape, (4, 50))




# ---------------------------------------------------------------------------
# Legal-mask tests
# ---------------------------------------------------------------------------


class TestLegalMask(unittest.TestCase):
    def test_legal_keys_to_labels_move(self):
        from showdown_ai.phase7_1_bc_warmstart_train_local import _legal_keys_to_labels
        keys = [["move", "tailwind", "0", ""], ["move", "protect", "0", ""]]
        labels = _legal_keys_to_labels(keys)
        self.assertIn("move|tailwind|0", labels)
        self.assertIn("move|protect|0", labels)
        self.assertEqual(len(labels), 2)

    def test_legal_keys_to_labels_switch(self):
        from showdown_ai.phase7_1_bc_warmstart_train_local import _legal_keys_to_labels
        keys = [["switch", "charizard", "0", ""]]
        labels = _legal_keys_to_labels(keys)
        self.assertIn("switch|charizard", labels)

    def test_legal_keys_to_labels_empty(self):
        from showdown_ai.phase7_1_bc_warmstart_train_local import _legal_keys_to_labels
        self.assertEqual(len(_legal_keys_to_labels([])), 0)
        self.assertEqual(len(_legal_keys_to_labels(None)), 0)

    def test_build_legal_mask_coverage(self):
        from showdown_ai.phase7_1_bc_warmstart_train_local import build_legal_mask
        label_map = {"move|tailwind|0": 0, "move|protect|0": 1, "move|attack|1": 2}
        legal = {"move|tailwind|0", "move|protect|0"}
        mask = build_legal_mask(legal, label_map, 3)
        self.assertTrue(mask[0].item())
        self.assertTrue(mask[1].item())
        self.assertFalse(mask[2].item())

    def test_build_legal_mask_true_label_always_covered(self):
        """The true selected action must always be legal."""
        from showdown_ai.phase7_1_bc_warmstart_train_local import (
            build_legal_mask, _legal_keys_to_labels, _extract_action_label,
        )
        legal_keys = [["move", "tailwind", "0", ""], ["move", "protect", "0", ""]]
        selected = ["move", "tailwind", "0", ""]
        legal_labels = _legal_keys_to_labels(legal_keys)
        true_label = _extract_action_label(selected)
        label_map = {lbl: i for i, lbl in enumerate(sorted(legal_labels))}
        mask = build_legal_mask(legal_labels, label_map, len(label_map))
        self.assertIn(true_label, legal_labels,
                      "true selected action must be in legal set")
        idx = label_map.get(true_label)
        self.assertIsNotNone(idx)
        self.assertTrue(mask[idx].item(),
                        "true action must be masked as legal")


if __name__ == "__main__":
    unittest.main()
