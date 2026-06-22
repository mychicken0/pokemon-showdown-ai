"""PLANNER-SPREAD-1B — Tests for SPREAD_MOVES allowlist fix.

Test-first: these tests are written BEFORE the fix.

Validates:
- True spread moves (per showdown target) DO fire SPREAD_DEFENSE
- False positives (single-target moves) do NOT fire SPREAD_DEFENSE

Source of truth: showdown data/moves.ts
  Spread targets: "allAdjacent", "allAdjacentFoes", "all"
  Single-target: "normal", "any", "self", etc.

True spread moves (19):
  heatwave, dazzlinggleam, earthquake, rockslide,
  bleakwindstorm, boomburst, discharge, eruption, glaciate,
  makeitrain, matchagotcha, muddywater, sandsearstorm,
  sludgewave, snarl, springtidestorm, surf, wildboltstorm

False positives removed (14):
  waterpulse, alluringvoice, drainingkiss, heatcrash,
  infernalparade, luminacrash, mudshot, mudslap,
  mysticalfire, powergem, ruination, syrupbomb,
  temperflare, thundercage, torchsong
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from bot_doubles_intent_classifier import (
    IntentDetector,
    SPREAD_DEFENSE,
    EVIDENCE_REVEALED_MOVES,
    ROUTE_SPREAD_DEFENSE,
)


def make_ctx(revealed_moves):
    """Build a context with revealed moves."""
    return {
        "opp_revealed_moves": revealed_moves,
        "fields": [],
        "side_conditions": [],
        "opp_used_tr": False,
        "opp_used_tw": False,
        "opp_used_stat_boost": False,
        "opp_pressure": False,
        "active_user_hp_fraction": 1.0,
        "expected_to_faint": False,
        "target_already_taunted": False,
    }


# True spread moves (validated against showdown data/moves.ts)
# These MUST fire SPREAD_DEFENSE
TRUE_SPREAD_MOVES = [
    "heatwave", "dazzlinggleam", "earthquake", "rockslide",
    "bleakwindstorm", "boomburst", "discharge", "eruption",
    "glaciate", "makeitrain", "matchagotcha", "muddywater",
    "sandsearstorm", "sludgewave", "snarl", "springtidestorm",
    "surf", "wildboltstorm",
]

# False positives (single-target moves that should NOT fire SPREAD_DEFENSE)
# Per PLANNER-SPREAD-1 design
FALSE_POSITIVES = [
    "waterpulse", "alluringvoice", "drainingkiss", "heatcrash",
    "infernalparade", "luminacrash", "mudshot", "mudslap",
    "mysticalfire", "powergem", "ruination", "syrupbomb",
    "temperflare", "thundercage", "torchsong",
]


class TestTrueSpreadMoves(unittest.TestCase):
    """True spread moves (per showdown target) MUST fire SPREAD_DEFENSE."""

    def test_heatwave_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["heatwave"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertEqual(d.evidence_source, EVIDENCE_REVEALED_MOVES)
        self.assertEqual(d.routed_to_policy, ROUTE_SPREAD_DEFENSE)
        self.assertIn("heatwave", d.matched_moves)

    def test_dazzlinggleam_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["dazzlinggleam"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("dazzlinggleam", d.matched_moves)

    def test_earthquake_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["earthquake"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("earthquake", d.matched_moves)

    def test_rockslide_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["rockslide"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("rockslide", d.matched_moves)

    def test_bleakwindstorm_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["bleakwindstorm"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("bleakwindstorm", d.matched_moves)

    def test_boomburst_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["boomburst"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("boomburst", d.matched_moves)

    def test_discharge_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["discharge"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("discharge", d.matched_moves)

    def test_eruption_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["eruption"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("eruption", d.matched_moves)

    def test_glaciate_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["glaciate"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("glaciate", d.matched_moves)

    def test_makeitrain_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["makeitrain"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("makeitrain", d.matched_moves)

    def test_matchagotcha_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["matchagotcha"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("matchagotcha", d.matched_moves)

    def test_muddywater_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["muddywater"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("muddywater", d.matched_moves)

    def test_sandsearstorm_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["sandsearstorm"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("sandsearstorm", d.matched_moves)

    def test_sludgewave_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["sludgewave"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("sludgewave", d.matched_moves)

    def test_snarl_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["snarl"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("snarl", d.matched_moves)

    def test_springtidestorm_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["springtidestorm"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("springtidestorm", d.matched_moves)

    def test_surf_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["surf"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("surf", d.matched_moves)

    def test_wildboltstorm_fires_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["wildboltstorm"]))
        self.assertEqual(d.intent, SPREAD_DEFENSE)
        self.assertIn("wildboltstorm", d.matched_moves)


class TestFalsePositivesRemoved(unittest.TestCase):
    """False positive moves (per showdown target) MUST NOT fire SPREAD_DEFENSE."""

    def test_waterpulse_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["waterpulse"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_alluringvoice_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["alluringvoice"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_drainingkiss_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["drainingkiss"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_heatcrash_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["heatcrash"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_infernalparade_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["infernalparade"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_luminacrash_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["luminacrash"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_mudshot_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["mudshot"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_mudslap_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["mudslap"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_mysticalfire_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["mysticalfire"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_powergem_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["powergem"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_ruination_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["ruination"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_syrupbomb_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["syrupbomb"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_temperflare_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["temperflare"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_thundercage_no_spread_defense(self):
        det = IntentDetector()
        d = det.detect(make_ctx(["thundercage"]))
        self.assertEqual(d.intent, "NO_INTENT")

    def test_torchsong_no_spread_defense(self):
        # torchsong is in STAT_BOOST_MOVES, so it fires ANTI_STAT_BOOST, not NO_INTENT.
        # The key assertion is: torchsong does NOT fire SPREAD_DEFENSE.
        det = IntentDetector()
        d = det.detect(make_ctx(["torchsong"]))
        self.assertNotEqual(d.intent, SPREAD_DEFENSE)


class TestSPREADMOVESAllowlist(unittest.TestCase):
    """Verify the SPREAD_MOVES set matches showdown's spread-target moves."""

    def test_allowlist_count(self):
        # 18 true spread moves (per showdown data/moves.ts, Gen 9 common ones)
        # Note: showdown has 100+ spread moves total but we only include
        # the most common Gen 9 ones (matching the bot's likely opponents).
        self.assertEqual(len(IntentDetector.SPREAD_MOVES), 18)

    def test_no_false_positives_in_allowlist(self):
        for fp in FALSE_POSITIVES:
            self.assertNotIn(
                fp, IntentDetector.SPREAD_MOVES,
                f"{fp} is in SPREAD_MOVES but is a false positive",
            )

    def test_all_true_spreads_in_allowlist(self):
        for ts in TRUE_SPREAD_MOVES:
            self.assertIn(
                ts, IntentDetector.SPREAD_MOVES,
                f"{ts} is a true spread move but not in SPREAD_MOVES",
            )


if __name__ == "__main__":
    unittest.main()
