#!/usr/bin/env python3
"""
Unit tests for Showdown Species Name Normalizer
"""

import unittest
from team_scrapers.showdown_name_normalizer import (
    normalize_species,
    DISPLAY_TO_SHOWDOWN,
    normalize_team_species,
    validate_species_exists
)


class TestShowdownNameNormalizer(unittest.TestCase):
    """Test cases for species name normalization."""

    def test_base_forms(self):
        """Test base form species normalization."""
        self.assertEqual(normalize_species("Abomasnow"), "abomasnow")
        self.assertEqual(normalize_species("Aegislash"), "aegislash")
        self.assertEqual(normalize_species("Garchomp"), "garchomp")
        self.assertEqual(normalize_species("Incineroar"), "incineroar")

    def test_alolan_forms(self):
        """Test Alolan form species normalization."""
        self.assertEqual(normalize_species("Alolan Ninetales"), "ninetalesalola")

    def test_hisuian_forms(self):
        """Test Hisuian form species normalization."""
        self.assertEqual(normalize_species("Arcanine [Hisuian Form]"), "arcaninehisui")
        self.assertEqual(normalize_species("Hisuian Arcanine"), "arcaninehisui")
        self.assertEqual(normalize_species("Hisuian Goodra"), "goodrahisui")
        self.assertEqual(normalize_species("Hisuian Samurott"), "samurotthisui")
        self.assertEqual(normalize_species("Hisuian Zoroark"), "zoroarkhisui")

    def test_eternal_flower_floette(self):
        """Test Eternal Flower Floette normalization."""
        self.assertEqual(normalize_species("Eternal Flower Floette"), "floetteeternal")
        self.assertEqual(normalize_species("Floette [Eternal Flower]"), "floetteeternal")

    def test_sinistcha_forms(self):
        """Test Sinistcha form normalization."""
        self.assertEqual(normalize_species("Sinistcha"), "sinistcha")
        self.assertEqual(normalize_species("Sinistcha [Unremarkable Form]"), "sinistcha")
        self.assertEqual(normalize_species("Sinistcha [Masterpiece Form]"), "sinistchamasterpiece")

    def test_rotom_forms(self):
        """Test Rotom form normalization."""
        self.assertEqual(normalize_species("Heat Rotom"), "rotomheat")
        self.assertEqual(normalize_species("Wash Rotom"), "rotomwash")
        self.assertEqual(normalize_species("Mow Rotom"), "rotommow")
        self.assertEqual(normalize_species("Fan Rotom"), "rotomfan")
        self.assertEqual(normalize_species("Frost Rotom"), "rotomfrost")
        self.assertEqual(normalize_species("Rotom [Wash Rotom]"), "rotomwash")

    def test_basculegion_forms(self):
        """Test Basculegion form normalization."""
        self.assertEqual(normalize_species("Basculegion"), "basculegion")
        self.assertEqual(normalize_species("Basculegion ♀"), "basculegionf")
        self.assertEqual(normalize_species("Basculegion-F"), "basculegionf")

    def test_paldean_tauros_forms(self):
        """Test Paldean Tauros form normalization."""
        self.assertEqual(normalize_species("Paldean Tauros Aqua Breed"), "taurospaldeaaqua")
        self.assertEqual(normalize_species("Paldean Tauros Blaze Breed"), "taurospaldeablaze")
        self.assertEqual(normalize_species("Paldean Tauros Combat Breed"), "taurospaldeacombat")

    def test_urshifu_forms(self):
        """Test Urshifu form normalization."""
        self.assertEqual(normalize_species("Urshifu [Single Strike]"), "urshifusingle")
        self.assertEqual(normalize_species("Urshifu [Rapid Strike]"), "urshifurapid")

    def test_ogerpon_forms(self):
        """Test Ogerpon form normalization."""
        self.assertEqual(normalize_species("Ogerpon [Teal Mask]"), "ogerpon")
        self.assertEqual(normalize_species("Ogerpon [Wellspring Mask]"), "ogerponwellspring")
        self.assertEqual(normalize_species("Ogerpon [Hearthflame Mask]"), "ogerponhearthflame")
        self.assertEqual(normalize_species("Ogerpon [Cornerstone Mask]"), "ogerponcornerstone")

    def test_calyrex_forms(self):
        """Test Calyrex form normalization."""
        self.assertEqual(normalize_species("Calyrex [Ice Rider]"), "calyrexice")
        self.assertEqual(normalize_species("Calyrex [Shadow Rider]"), "calyrexshadow")

    def test_terapagos_forms(self):
        """Test Terapagos form normalization."""
        self.assertEqual(normalize_species("Terapagos [Normal]"), "terapagos")
        self.assertEqual(normalize_species("Terapagos [Terastal]"), "terapagostera")
        self.assertEqual(normalize_species("Terapagos [Stellar]"), "terapagosstellar")

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        self.assertEqual(normalize_species("garchomp"), "garchomp")
        self.assertEqual(normalize_species("GARCHOMP"), "garchomp")
        self.assertEqual(normalize_species("GaRcHoMp"), "garchomp")

    def test_bracket_removal(self):
        """Test that brackets are handled properly."""
        self.assertEqual(normalize_species("Arcanine [Hisuian Form]"), "arcaninehisui")
        self.assertEqual(normalize_species("Floette [Eternal Flower]"), "floetteeternal")

    def test_unknown_species(self):
        """Test that unknown species return None."""
        self.assertIsNone(normalize_species("Unknown Pokemon"))
        self.assertIsNone(normalize_species(""))

    def test_validate_species_exists(self):
        """Test species validation."""
        self.assertTrue(validate_species_exists("garchomp"))
        self.assertTrue(validate_species_exists("arcaninehisui"))
        self.assertFalse(validate_species_exists("nonexistent"))

    def test_normalize_team_species(self):
        """Test normalizing a full team."""
        team = [
            {"species": "Garchomp", "moves": ["Earthquake"]},
            {"species": "Arcanine [Hisuian Form]", "moves": ["Flare Blitz"]},
            {"species": "Basculegion ♀", "moves": ["Wave Crash"]},
        ]
        normalized = normalize_team_species(team)
        self.assertEqual(normalized[0]["species"], "garchomp")
        self.assertEqual(normalized[0]["showdown_species_id"], "garchomp")
        self.assertEqual(normalized[1]["species"], "arcaninehisui")
        self.assertEqual(normalized[1]["showdown_species_id"], "arcaninehisui")
        self.assertEqual(normalized[2]["species"], "basculegionf")
        self.assertEqual(normalized[2]["showdown_species_id"], "basculegionf")


if __name__ == "__main__":
    unittest.main()