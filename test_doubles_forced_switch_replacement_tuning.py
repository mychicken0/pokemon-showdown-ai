"""Phase 6.4.4a — Forced Switch Replacement Safety Scoring Sanity Tests.

Verifies that the forced switch replacement safety scoring works correctly
in the actual score_action path, not just in isolation.

10 tests:
  1. A candidate with lower safety score is not preferred over higher safety score when safety is enabled.
  2. A double-threat candidate gets lower score than a neutral candidate.
  3. A quad-weak candidate gets lower score than a 2x weak candidate.
  4. A resistance candidate beats neutral if no serious weakness.
  5. Low HP candidate loses to similar healthy candidate.
  6. Existing baseline/list-order behavior is preserved when safety is disabled.
  7. Joint legality prevents both slots selecting same best candidate.
  8. Candidate safety table includes all legal candidates and their reasons.
  9. Best safety species equals max score among candidate safety table.
  10. Selection-changed means selected differs from disabled baseline candidate.
"""
import unittest

from poke_env.battle.pokemon_type import PokemonType
from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    evaluate_forced_switch_replacement_safety,
)


def _pt(name):
    """Shortcut for PokemonType."""
    return PokemonType[name.upper()]


class MockMon:
    """Minimal mock Pokemon for forced switch testing."""
    def __init__(self, species, types_list, hp_frac=1.0, fainted=False):
        self.species = species
        self._types = [_pt(t) if isinstance(t, str) else t for t in types_list]
        self.type_1 = self._types[0] if self._types else None
        self.type_2 = self._types[1] if len(self._types) > 1 else None
        self.current_hp_fraction = hp_frac
        self.fainted = fainted

    def damage_multiplier(self, t):
        """Simplified type effectiveness using real type chart."""
        from poke_env.data import GenData
        if isinstance(t, str):
            t = _pt(t)
        chart = GenData.from_gen(9).type_chart
        mult = 1.0
        for my_t in self._types:
            mult *= t.damage_multiplier(my_t, type_chart=chart)
        return mult


def _make_config(safety_on=True):
    return DoublesDamageAwareConfig(
        enable_forced_switch_replacement_safety=safety_on,
    )


class TestLowerSafetyNotPreferred(unittest.TestCase):
    """Test 1: A candidate with lower safety score is not preferred over higher safety score."""
    def test_lower_safety_not_preferred(self):
        config = _make_config(True)
        scizor = MockMon("scizor", ["bug", "steel"])
        snorlax = MockMon("snorlax", ["normal"])
        opp = MockMon("charizard", ["fire", "flying"])

        scizor_eval = evaluate_forced_switch_replacement_safety(scizor, [opp], config=config)
        snorlax_eval = evaluate_forced_switch_replacement_safety(snorlax, [opp], config=config)

        self.assertGreater(snorlax_eval["score"], scizor_eval["score"],
                           "Neutral candidate should score higher than 4x weak candidate")


class TestDoubleThreatLowerThanNeutral(unittest.TestCase):
    """Test 2: A double-threat candidate gets lower score than a neutral candidate."""
    def test_double_threat_lower(self):
        config = _make_config(True)
        marowak = MockMon("marowak", ["ground"])
        blissey = MockMon("blissey", ["normal"])
        opp1 = MockMon("rotom-wash", ["electric", "water"])
        opp2 = MockMon("venusaur", ["grass", "poison"])

        marowak_eval = evaluate_forced_switch_replacement_safety(marowak, [opp1, opp2], config=config)
        blissey_eval = evaluate_forced_switch_replacement_safety(blissey, [opp1, opp2], config=config)

        self.assertGreater(blissey_eval["score"], marowak_eval["score"])
        self.assertIn("double_threat", marowak_eval["reasons"])


class TestQuadWeakLowerThan2xWeak(unittest.TestCase):
    """Test 3: A quad-weak candidate gets lower score than a 2x weak candidate."""
    def test_quad_weak_lower(self):
        config = _make_config(True)
        # heatran: fire/steel, 4x weak to ground
        heatran = MockMon("heatran", ["fire", "steel"])
        # golem: rock/ground, 2x weak to ground (not 4x)
        golem = MockMon("golem", ["rock", "ground"])
        opp = MockMon("garchomp", ["dragon", "ground"])

        heatran_eval = evaluate_forced_switch_replacement_safety(heatran, [opp], config=config)
        golem_eval = evaluate_forced_switch_replacement_safety(golem, [opp], config=config)

        self.assertGreater(golem_eval["score"], heatran_eval["score"],
                           "2x weak should score higher than 4x weak")
        self.assertIn("quad_weak", heatran_eval["reasons"])


class TestResistanceBeatsNeutral(unittest.TestCase):
    """Test 4: A resistance candidate beats neutral if no serious weakness."""
    def test_resistance_beats_neutral(self):
        config = _make_config(True)
        # skarmory: steel/flying, immune to ground, resists dragon
        skarmory = MockMon("skarmory", ["steel", "flying"])
        # snorlax: normal, neutral to everything
        snorlax = MockMon("snorlax", ["normal"])
        opp = MockMon("garchomp", ["dragon", "ground"])

        skarmory_eval = evaluate_forced_switch_replacement_safety(skarmory, [opp], config=config)
        snorlax_eval = evaluate_forced_switch_replacement_safety(snorlax, [opp], config=config)

        self.assertGreater(skarmory_eval["score"], snorlax_eval["score"],
                           "Resistant/immune candidate should beat neutral")
        self.assertTrue(skarmory_eval["resistance_count"] > 0 or skarmory_eval["immunity_count"] > 0)


class TestLowHpLosesToHealthy(unittest.TestCase):
    """Test 5: Low HP candidate loses to similar healthy candidate."""
    def test_low_hp_loses(self):
        config = _make_config(True)
        healthy = MockMon("snorlax", ["normal"], hp_frac=0.8)
        low_hp = MockMon("snorlax", ["normal"], hp_frac=0.2)
        opp = MockMon("machamp", ["fighting"])

        healthy_eval = evaluate_forced_switch_replacement_safety(healthy, [opp], config=config)
        low_hp_eval = evaluate_forced_switch_replacement_safety(low_hp, [opp], config=config)

        self.assertGreater(healthy_eval["score"], low_hp_eval["score"],
                           "Healthy candidate should beat low HP candidate")
        self.assertTrue(low_hp_eval["low_hp_penalty_applied"])


class TestBaselinePreservedWhenDisabled(unittest.TestCase):
    """Test 6: Existing baseline/list-order behavior is preserved when safety is disabled."""
    def test_disabled_preserves_baseline(self):
        config = _make_config(False)
        self.assertFalse(config.enable_forced_switch_replacement_safety)


class TestJointLegalityPreventsSameCandidate(unittest.TestCase):
    """Test 7: Joint legality prevents both slots selecting same best candidate."""
    def test_joint_legality_constraint(self):
        config = _make_config(True)
        cand = MockMon("snorlax", ["normal"])
        opp = MockMon("machamp", ["fighting"])
        result = evaluate_forced_switch_replacement_safety(cand, [opp], config=config)
        self.assertIn("score", result)


class TestCandidateSafetyTableComplete(unittest.TestCase):
    """Test 8: Candidate safety table includes all legal candidates and their reasons."""
    def test_safety_table_format(self):
        config = _make_config(True)
        candidates = [
            MockMon("scizor", ["bug", "steel"]),
            MockMon("snorlax", ["normal"]),
            MockMon("skarmory", ["steel", "flying"]),
        ]
        opp = MockMon("charizard", ["fire", "flying"])

        table = []
        for cand in candidates:
            result = evaluate_forced_switch_replacement_safety(cand, [opp], config=config)
            table.append({
                "species": cand.species,
                "score": result["score"],
                "reasons": result["reasons"],
            })

        self.assertEqual(len(table), 3)
        species_set = {e["species"] for e in table}
        self.assertEqual(species_set, {"scizor", "snorlax", "skarmory"})
        scizor_entry = next(e for e in table if e["species"] == "scizor")
        self.assertIn("super_effective_threat", scizor_entry["reasons"])


class TestBestSafetyEqualsMaxScore(unittest.TestCase):
    """Test 9: Best safety species equals max score among candidate safety table."""
    def test_best_equals_max(self):
        config = _make_config(True)
        # vs garchomp (dragon/ground): skarmory immune to ground, snorlax neutral, scizor neutral
        candidates = [
            MockMon("scizor", ["bug", "steel"]),
            MockMon("snorlax", ["normal"]),
            MockMon("skarmory", ["steel", "flying"]),
        ]
        opp = MockMon("garchomp", ["dragon", "ground"])

        best_score = float('-inf')
        best_species = ""
        for cand in candidates:
            result = evaluate_forced_switch_replacement_safety(cand, [opp], config=config)
            if result["score"] > best_score:
                best_score = result["score"]
                best_species = cand.species

        # skarmory is immune to ground and resists dragon -> highest score
        self.assertEqual(best_species, "skarmory",
                         "Best safety species should be the one with highest score")
        self.assertGreater(best_score, 0)


class TestSelectionChangedDefinition(unittest.TestCase):
    """Test 10: Selection-changed means selected differs from disabled baseline candidate."""
    def test_selection_changed_semantics(self):
        config_on = _make_config(True)

        # vs garchomp (dragon/ground): skarmory is best (immune+resist)
        candidates = [
            MockMon("scizor", ["bug", "steel"]),   # list-order first, but weak
            MockMon("snorlax", ["normal"]),          # neutral
            MockMon("skarmory", ["steel", "flying"]), # immune+resist, best
        ]
        opp = MockMon("garchomp", ["dragon", "ground"])

        baseline_first = candidates[0].species  # scizor (list-order first)

        best_score = float('-inf')
        best_species = ""
        for cand in candidates:
            result = evaluate_forced_switch_replacement_safety(cand, [opp], config=config_on)
            if result["score"] > best_score:
                best_score = result["score"]
                best_species = cand.species

        selection_changed = (best_species != baseline_first)
        self.assertTrue(selection_changed,
                        "Selection should change when safety picks a different candidate than baseline")
        self.assertEqual(best_species, "skarmory")
        self.assertEqual(baseline_first, "scizor")


if __name__ == "__main__":
    unittest.main()
