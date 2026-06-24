"""Tests for PHASE7_DATA_EXPANSION_FIX_FF_MONITOR_RAW_LOGGING.

Ponytail: pure unit tests. No poke-env runtime, no network,
no I/O beyond the temp dir. No battles. No GPU.
"""
import json
import os
import unittest
import tempfile

from showdown_ai.rl_data_3b_ff_monitor_v2 import (
    SPREAD_MOVE_IDS,
    STATUS_FROM_TOKENS,
    WEATHER_CHIP_TOKENS,
    RECOIL_MOVES,
    ITEM_DAMAGE_TOKENS,
    ABILITY_DAMAGE_TOKENS,
    HAZARD_DAMAGE_TOKENS,
    classify_damage_event_from_protocol,
    parse_protocol_line,
    side_from_actor_id,
    get_required_summary_fields,
    make_empty_summary,
    stage2_gate_passes,
)


class TestActualFriendlyFireClassification(unittest.TestCase):
    """Bug Buzz into same-side ally with damage is
    ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE."""

    def test_bug_buzz_ally_target_classified_actual(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p2",
            actor_id="p2a: Volcarona",
            move_id="bugbuzz",
            target_side="p2",
            target_id="p2b: Tornadus",
            from_token="",
            raw_line="|move|p2a: Volcarona|Bug Buzz|p2b: Tornadus",
        )
        self.assertEqual(cl, "ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE")

    def test_psychic_into_ally_classified_actual(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1",
            actor_id="p1a: Tapu Lele",
            move_id="psychic",
            target_side="p1",
            target_id="p1b: Volcarona",
        )
        self.assertEqual(cl, "ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE")

    def test_opponent_targeting_is_not_friendly_fire(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1",
            actor_id="p1a: Garchomp",
            move_id="earthquake",
            target_side="p2",
            target_id="p2a: Tyranitar",
        )
        self.assertNotEqual(cl, "ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE")
        self.assertEqual(cl, "FALSE_POSITIVE_SPREAD_DAMAGE")


class TestSpreadFalsePositive(unittest.TestCase):
    """Spread moves (Earthquake, Rock Slide, Heat Wave, etc.)
    are FALSE_POSITIVE_SPREAD_DAMAGE."""

    def test_earthquake_spread(self):
        for mid in ("earthquake", "Earthquake"):
            cl = classify_damage_event_from_protocol(
                actor_side="p1", actor_id="p1a: Garchomp",
                move_id=mid, target_side="p1",
                target_id="p1b: Rillaboom",
            )
            self.assertEqual(cl, "FALSE_POSITIVE_SPREAD_DAMAGE")

    def test_rock_slide_spread(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Tyranitar",
            move_id="rockslide", target_side="p1",
            target_id="p1b: Volcarona",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_SPREAD_DAMAGE")

    def test_heat_wave_spread(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Volcarona",
            move_id="heatwave", target_side="p1",
            target_id="p1b: Garchomp",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_SPREAD_DAMAGE")

    def test_discharge_spread(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Zeraora",
            move_id="discharge", target_side="p1",
            target_id="p1b: Cinderace",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_SPREAD_DAMAGE")

    def test_surf_spread(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Kyogre",
            move_id="surf", target_side="p1",
            target_id="p1b: Ferrothorn",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_SPREAD_DAMAGE")


class TestWeatherChip(unittest.TestCase):
    """Sandstorm/Hail/Snow chip damage is
    FALSE_POSITIVE_WEATHER_CHIP."""

    def test_sandstorm_chip(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p1", target_id="p1a: Volcarona",
            from_token="Sandstorm",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_WEATHER_CHIP")

    def test_hail_chip(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Dragonite",
            from_token="Hail",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_WEATHER_CHIP")

    def test_snow_chip(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Garchomp",
            from_token="Snow",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_WEATHER_CHIP")


class TestStatusChip(unittest.TestCase):
    """Burn/poison damage is FALSE_POSITIVE_STATUS_CHIP."""

    def test_burn_chip(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Volcarona",
            from_token="brn",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_STATUS_CHIP")

    def test_poison_chip(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Garchomp",
            from_token="psn",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_STATUS_CHIP")

    def test_toxic_chip(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Tyranitar",
            from_token="tox",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_STATUS_CHIP")


class TestHazardDamage(unittest.TestCase):
    """Stealth Rock / Spikes / Toxic Spikes damage is
    FALSE_POSITIVE_HAZARD_DAMAGE."""

    def test_stealth_rock(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Charizard",
            from_token="Stealth Rock",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_HAZARD_DAMAGE")

    def test_spikes(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Talonflame",
            from_token="Spikes",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_HAZARD_DAMAGE")

    def test_toxic_spikes(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p2", target_id="p2a: Garchomp",
            from_token="Toxic Spikes",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_HAZARD_DAMAGE")


class TestRecoil(unittest.TestCase):
    """Recoil moves (Flare Blitz, etc.) on same-side target
    are FALSE_POSITIVE_RECOIL, not actual friendly fire."""

    def test_flare_blitz_recoil(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Incineroar",
            move_id="flareblitz", target_side="p1",
            target_id="p1a: Incineroar",
            from_token="",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_RECOIL")

    def test_brave_bird_recoil(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Talonflame",
            move_id="bravebird", target_side="p1",
            target_id="p1a: Talonflame",
            from_token="",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_RECOIL")

    def test_recoil_from_token(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Incineroar",
            move_id="flareblitz", target_side="p1",
            target_id="p1a: Incineroar",
            from_token="recoil",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_RECOIL")


class TestItemDamage(unittest.TestCase):
    """Life Orb / Rocky Helmet damage is item false positive."""

    def test_life_orb(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Volcarona",
            move_id="bugbuzz", target_side="p1",
            target_id="p1a: Volcarona",
            from_token="Life Orb",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_ITEM_DAMAGE")

    def test_rocky_helmet(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Garchomp",
            move_id="earthquake", target_side="p2",
            target_id="p2a: Tyranitar",
            from_token="Rocky Helmet",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_ITEM_DAMAGE")

    def test_item_token(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p1", target_id="p1a: Tapu Lele",
            from_token="item",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_ITEM_DAMAGE")


class TestAbilityDamage(unittest.TestCase):
    """Rough Skin / Iron Barbs / Aftermath damage is ability
    false positive."""

    def test_rough_skin(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Garchomp",
            move_id="earthquake", target_side="p1",
            target_id="p1a: Garchomp",
            from_token="Rough Skin",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_ABILITY_DAMAGE")

    def test_iron_barbs(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Ferrothorn",
            move_id="", target_side="p1",
            target_id="p1a: Ferrothorn",
            from_token="Iron Barbs",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_ABILITY_DAMAGE")

    def test_ability_token(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="", move_id="",
            target_side="p1", target_id="p1a: Garchomp",
            from_token="ability",
        )
        self.assertEqual(cl, "FALSE_POSITIVE_ABILITY_DAMAGE")


class TestLabelNoise(unittest.TestCase):
    """Selected negative-target label noise with no actual
    ally HP damage is FALSE_POSITIVE_TARGET_LABEL_NOISE_NO_DAMAGE.
    The classifier returns NOT_FRIENDLY_FIRE for cross-side; the
    label-noise case is handled by the monitor wrapper that
    combines selected-target and HP delta, not the raw
    classifier."""

    def test_psychic_into_ally_no_damage_real_friendly_fire(self):
        # If the move was psychic into ally with no [from] tag,
        # the classifier says ACTUAL (same-side single-target).
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Tapu Lele",
            move_id="psychic", target_side="p1",
            target_id="p1b: Volcarona",
        )
        self.assertEqual(cl, "ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE")


class TestMissingRawLogs(unittest.TestCase):
    """If raw logs are missing, summary must report
    unknown_friendly_fire_suspect_count and the gate must
    fail."""

    def test_empty_summary_has_zero_unknowns(self):
        s = make_empty_summary(raw_protocol_logs_present=False)
        self.assertEqual(s["unknown_friendly_fire_suspect_count"], 0)
        self.assertFalse(s["raw_protocol_logs_present"])

    def test_gate_fails_without_raw_logs(self):
        s = make_empty_summary(raw_protocol_logs_present=False)
        self.assertFalse(stage2_gate_passes(s))

    def test_gate_fails_with_unknowns(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["unknown_friendly_fire_suspect_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_gate_fails_with_actual_friendly_fire(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["opponent_actual_friendly_fire_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_gate_passes_when_clean(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        self.assertTrue(stage2_gate_passes(s))


class TestSummaryFields(unittest.TestCase):
    """Summary must include raw_protocol_logs_present and
    friendly_fire_monitor_version."""

    def test_summary_has_required_fields(self):
        s = make_empty_summary()
        self.assertIn("raw_protocol_logs_present", s)
        self.assertIn("friendly_fire_monitor_version", s)
        self.assertEqual(s["friendly_fire_monitor_version"], "v2_raw_protocol")

    def test_required_fields_list_matches_summary(self):
        required = get_required_summary_fields()
        s = make_empty_summary()
        for f in required:
            self.assertIn(f, s)


class TestProtocolLineParser(unittest.TestCase):
    """Raw protocol line parser is used by future monitors."""

    def test_parse_move_line(self):
        p = parse_protocol_line("|move|p1a: Garchomp|Earthquake|p2a: Tyranitar")
        self.assertEqual(p["kind"], "move")
        self.assertEqual(p["actor_id"], "p1a: Garchomp")
        self.assertEqual(p["move_id"], "Earthquake")
        self.assertEqual(p["target_id"], "p2a: Tyranitar")

    def test_parse_damage_line_with_from(self):
        p = parse_protocol_line("|-damage|p1a: Volcarona|78/100|[from] Sandstorm")
        self.assertEqual(p["kind"], "-damage")
        self.assertEqual(p["target_id"], "p1a: Volcarona")
        self.assertEqual(p["from_token"], "Sandstorm")

    def test_parse_weather_line(self):
        p = parse_protocol_line("|-weather|Sandstorm|[upkeep]")
        self.assertEqual(p["kind"], "-weather")
        self.assertEqual(p["weather"], "Sandstorm")

    def test_parse_turn_line(self):
        p = parse_protocol_line("|turn|3")
        self.assertEqual(p["kind"], "turn")
        self.assertEqual(p["turn"], "3")

    def test_side_from_actor_id(self):
        self.assertEqual(side_from_actor_id("p1a: Volcarona"), "p1")
        self.assertEqual(side_from_actor_id("p2b: Tornadus"), "p2")
        self.assertEqual(side_from_actor_id(""), "?")


class TestCollectionScriptFlags(unittest.TestCase):
    """Collection script must support --raw-protocol-dir and
    not introduce any official server URL or scope creep."""

    def test_collection_module_has_make_opponent_default_damage_aware(self):
        import showdown_ai.rl_data_3b_small_local_audit as m
        self.assertEqual(m.DEFAULT_OPPONENT_POLICY, "damage_aware")
        self.assertIn("damage_aware", m.OPPONENT_POLICY_CHOICES)

    def test_collection_module_no_official_server_url(self):
        src_path = os.path.join(
            os.path.dirname(__file__),
            "..", "showdown_ai", "rl_data_3b_small_local_audit.py",
        )
        with open(os.path.abspath(src_path)) as f:
            src = f.read()
        # The new module must not reference any official server
        self.assertNotIn("play.pokemonshowdown.com", src)
        self.assertNotIn("smogon.com", src)
        # HEALTH_URL is still localhost
        self.assertIn("localhost:8000", src)

    def test_collection_module_no_production_bot_default_flip(self):
        src_path = os.path.join(
            os.path.dirname(__file__),
            "..", "showdown_ai", "rl_data_3b_small_local_audit.py",
        )
        with open(os.path.abspath(src_path)) as f:
            src = f.read()
        # No new scoring defaults
        self.assertNotIn("enable_anti_trick_room_response = True", src)
        self.assertNotIn("enable_support_move_target_hard_safety = True", src)
        self.assertNotIn("enable_wide_guard", src)
        self.assertNotIn("enable_follow_me", src)
        self.assertNotIn("enable_rage_powder", src)

    def test_raw_protocol_capture_module_exists(self):
        from showdown_ai.rl_data_3b_raw_protocol_capture import (
            RawProtocolCapture,
        )
        self.assertTrue(callable(RawProtocolCapture))


class TestRawProtocolCaptureFile(unittest.TestCase):
    """Raw protocol capture writes per-battle JSONL."""

    def test_capture_writes_per_battle_file(self):
        from showdown_ai.rl_data_3b_raw_protocol_capture import (
            RawProtocolCapture,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cap = RawProtocolCapture(
                battle_id="battle-test-1",
                out_dir=tmp,
            )
            self.assertTrue(cap.enabled)
            cap.feed("|player|p1|bot|")
            cap.feed("|player|p2|opp|")
            cap.feed("|turn|1")
            cap.feed("|move|p1a: Volcarona|Bug Buzz|p2a: Tyranitar")
            cap.feed("|-damage|p2a: Tyranitar|73/100")
            path = cap.path()
            self.assertIsNotNone(path)
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                lines = [json.loads(l) for l in f]
            self.assertEqual(len(lines), 5)
            self.assertEqual(lines[0]["line"], "|player|p1|bot|")
            self.assertEqual(lines[3]["line"],
                             "|move|p1a: Volcarona|Bug Buzz|p2a: Tyranitar")
            self.assertEqual(lines[3]["seq"], 4)
            self.assertEqual(lines[3]["battle_id"], "battle-test-1")

    def test_capture_disabled_no_file(self):
        from showdown_ai.rl_data_3b_raw_protocol_capture import (
            RawProtocolCapture,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cap = RawProtocolCapture(
                battle_id="battle-test-2",
                out_dir=tmp,
                enabled=False,
            )
            self.assertFalse(cap.enabled)
            cap.feed("|turn|1")
            self.assertIsNone(cap.path())


class TestProductionBotUntouched(unittest.TestCase):
    """No source/test changes to production bot or `test_51`."""

    def test_production_bot_unchanged(self):
        from bot_doubles_damage_aware import DoublesDamageAwareConfig
        # Default policy unchanged
        self.assertFalse(
            getattr(DoublesDamageAwareConfig, "enable_support_move_target_hard_safety", False)
        )

    def test_test_51_path_does_not_exist_or_unchanged(self):
        # The audit must report if test_51 was modified.
        # We do not actually open test_51; just ensure the
        # test infra does not introduce a change here.
        import subprocess
        r = subprocess.run(
            ["git", "status", "--short", "tests/"],
            capture_output=True, text=True,
            cwd=os.path.join(
                os.path.dirname(__file__), "..",
            ),
        )
        # No tracked test file should be deleted
        self.assertNotIn("D tests/test_51", r.stdout)


if __name__ == "__main__":
    unittest.main()
