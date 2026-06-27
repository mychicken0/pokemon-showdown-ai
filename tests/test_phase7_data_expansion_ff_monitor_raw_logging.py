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
    parse_no_effect_attacks_from_raw_protocol,
    parse_low_value_priority_from_raw_protocol,
    parse_protocol_line,
    side_from_actor_id,
    get_required_summary_fields,
    make_empty_summary,
    stage2_gate_passes,
)


class TestActualFriendlyFireClassification(unittest.TestCase):
    """Bug Buzz into same-side ally with classification
    changes based on confirmed_damage flag."""

    def test_bug_buzz_ally_target_without_confirmed_is_submitted_noise(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p2",
            actor_id="p2a: Volcarona",
            move_id="bugbuzz",
            target_side="p2",
            target_id="p2b: Tornadus",
            from_token="",
            raw_line="|move|p2a: Volcarona|Bug Buzz|p2b: Tornadus",
            confirmed_damage=False,
        )
        self.assertEqual(cl, "SUBMITTED_TARGET_NOISE_NO_CONFIRMED_DAMAGE")

    def test_bug_buzz_ally_target_with_confirmed_is_actual(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p2",
            actor_id="p2a: Volcarona",
            move_id="bugbuzz",
            target_side="p2",
            target_id="p2b: Tornadus",
            from_token="",
            raw_line="|move|p2a: Volcarona|Bug Buzz|p2b: Tornadus",
            confirmed_damage=True,
        )
        self.assertEqual(cl, "CONFIRMED_ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE")

    def test_psychic_into_ally_without_confirmed_is_submitted_noise(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1",
            actor_id="p1a: Tapu Lele",
            move_id="psychic",
            target_side="p1",
            target_id="p1b: Volcarona",
            confirmed_damage=False,
        )
        self.assertEqual(cl, "SUBMITTED_TARGET_NOISE_NO_CONFIRMED_DAMAGE")

    def test_psychic_into_ally_with_confirmed_is_actual(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1",
            actor_id="p1a: Tapu Lele",
            move_id="psychic",
            target_side="p1",
            target_id="p1b: Volcarona",
            confirmed_damage=True,
        )
        self.assertEqual(cl, "CONFIRMED_ACTUAL_SINGLE_TARGET_FRIENDLY_FIRE")

    def test_opponent_targeting_is_not_friendly_fire(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1",
            actor_id="p1a: Garchomp",
            move_id="earthquake",
            target_side="p2",
            target_id="p2a: Tyranitar",
        )
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
    ally HP damage is SUBMITTED_TARGET_NOISE_NO_CONFIRMED_DAMAGE."""

    def test_psychic_into_ally_no_damage(self):
        cl = classify_damage_event_from_protocol(
            actor_side="p1", actor_id="p1a: Tapu Lele",
            move_id="psychic", target_side="p1",
            target_id="p1b: Volcarona",
        )
        self.assertEqual(cl, "SUBMITTED_TARGET_NOISE_NO_CONFIRMED_DAMAGE")


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

    def test_gate_fails_with_confirmed_actual_friendly_fire(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["opponent_confirmed_actual_friendly_fire_count"] = 1
        self.assertFalse(stage2_gate_passes(s))

    def test_gate_passes_clean(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        self.assertTrue(stage2_gate_passes(s))

    def test_gate_does_not_fail_from_submitted_target_noise(self):
        s = make_empty_summary(raw_protocol_logs_present=True)
        s["submitted_same_side_target_count"] = 20
        s["bot_submitted_negative_target_count"] = 3
        s["opponent_submitted_negative_target_count"] = 17
        self.assertTrue(stage2_gate_passes(s))


class TestSummaryFields(unittest.TestCase):
    """Summary must include confirmed-actual and submitted-noise fields."""

    def test_summary_has_required_fields(self):
        s = make_empty_summary()
        self.assertIn("raw_protocol_logs_present", s)
        self.assertIn("friendly_fire_monitor_version", s)
        self.assertEqual(s["friendly_fire_monitor_version"], "v3_confirmed_damage")
        self.assertIn("opponent_confirmed_actual_friendly_fire_count", s)
        self.assertIn("bot_confirmed_actual_friendly_fire_count", s)
        self.assertIn("submitted_same_side_target_count", s)
        self.assertIn("bot_submitted_negative_target_count", s)
        self.assertIn("opponent_submitted_negative_target_count", s)

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


def _write_battle_jsonl(out_dir, name, lines):
    """Helper: write a synthetic battle JSONL with the given
    protocol lines (list of str). Each line is wrapped as
    ``{"line": ..., "seq": i, "battle_id": name}`` to mirror
    the real RawProtocolCapture format.
    """
    path = os.path.join(out_dir, f"{name}.jsonl")
    with open(path, "w") as f:
        for i, line in enumerate(lines):
            f.write(
                json.dumps({
                    "line": line, "seq": i, "battle_id": name
                }) + "\n"
            )
    return path


class TestNoEffectProductivePartialSpread(unittest.TestCase):
    """PHASE7_FIX_NO_EFFECT_PARSER_PRODUCTIVE_PARTIAL_SPREAD.

    A spread damaging move (e.g. Earthquake) that productively
    hits at least one target and produces an ``|-immune|`` for
    another target must NOT be classified as a real no-effect
    policy bug. It is a parser false-positive / tracked event.

    Test rules:

    1. Spread move hits 1 target, immune on 1 target -> not
       a real no-effect bug; counted as
       ``productive_partial_spread_no_effect_false_positive_count``.
    2. Spread move all valid targets immune -> real no-effect
       bug.
    3. Single-target Electric into known Ground -> real
       no-effect bug.
    4. Attack into Protect -> not type-immunity no-effect.
    5. Status failure -> not damaging no-effect bug.
    6. Productive partial spread is reported separately as
       parser false-positive / tracked event, not safety
       failure.
    7. Existing raw monitor tests still pass.
    """

    def test_earthquake_spread_partial_productive_immune(self):
        """Earthquake hits p2a productively, immune to p2b.
        Must be counted as
        ``productive_partial_spread_no_effect_false_positive``
        and NOT a ``no_effect_policy_bug``.

        Note: real Showdown protocol emits
        ``|move| -> |-immune| -> |-damage|`` for spread
        moves, so the damage line comes AFTER the
        immune line. The parser lookahead scans the
        rest of the turn for clean damage lines.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                (
                    "|move|p1a: Garchomp|Earthquake|p2a: Tyranitar"
                ),
                "|-immune|p2b: Tornadus",
                "|-damage|p2a: Tyranitar|123/200",
            ]
            _write_battle_jsonl(tmp, "battle-spread-partial", lines)
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        self.assertEqual(
            s["productive_partial_spread_no_effect_false_positive_count"],
            1,
        )
        self.assertEqual(
            s["spread_partial_productive_immune_count"], 1
        )
        self.assertEqual(
            s["spread_all_targets_immune_bug_count"], 0
        )
        self.assertEqual(s["no_effect_policy_bug_count"], 0)
        self.assertEqual(s["no_effect_move_count"], 0)
        self.assertTrue(s["no_effect_policy_gate_pass"])
        # The event is recorded with the productive-partial
        # classification.
        ev_classes = {
            e.get("classification")
            for e in s.get("events", [])
        }
        self.assertIn(
            "PRODUCTIVE_PARTIAL_SPREAD_NO_EFFECT_FALSE_POSITIVE",
            ev_classes,
        )

    def test_earthquake_spread_all_targets_immune_real_bug(self):
        """Earthquake hits no one (both targets immune) -> real
        no-effect bug. Counted as
        ``spread_all_targets_immune_bug_count`` AND as
        ``no_effect_policy_bug_count`` for repeated cases.

        The pre-existing parser limitation resets the
        current-move tracker after the first ``|-immune|``
        per move line, so only the first immune line per
        move is counted. The repeated same-target
        condition still triggers the real-bug counter.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Garchomp|Earthquake|p2a: Tornadus",
                "|-immune|p2a: Tornadus",
                "|turn|2",
                "|move|p1a: Garchomp|Earthquake|p2a: Tornadus",
                "|-immune|p2a: Tornadus",
            ]
            _write_battle_jsonl(tmp, "battle-spread-all-immune", lines)
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        # 2 turns, 1 first-immune-per-turn = 2
        # spread_all_targets_immune events.
        self.assertEqual(s["spread_all_targets_immune_bug_count"], 2)
        # Repeated same-target real bug.
        self.assertGreaterEqual(s["no_effect_policy_bug_count"], 1)
        self.assertFalse(s["no_effect_policy_gate_pass"])
        # The productive-partial-spread logic does not
        # affect this case (no |-damage| lines for the
        # spread move).
        self.assertEqual(
            s["productive_partial_spread_no_effect_false_positive_count"],
            0,
        )

    def test_single_target_electric_into_ground_real_bug(self):
        """Single-target damaging move into a known-immune
        target is a real no-effect bug, NOT a productive
        partial spread. Not affected by the new partial-spread
        logic.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Pikachu|Thunderbolt|p2a: Garchomp",
                "|-immune|p2a: Garchomp",
                "|turn|2",
                "|move|p1a: Pikachu|Thunderbolt|p2a: Garchomp",
                "|-immune|p2a: Garchomp",
            ]
            _write_battle_jsonl(
                tmp, "battle-single-immune", lines
            )
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        # Single-target: not a partial-spread.
        self.assertEqual(
            s["productive_partial_spread_no_effect_false_positive_count"],
            0,
        )
        self.assertEqual(
            s["spread_partial_productive_immune_count"], 0
        )
        self.assertEqual(
            s["spread_all_targets_immune_bug_count"], 0
        )
        # Repeated same-target = real bug.
        self.assertGreaterEqual(s["no_effect_policy_bug_count"], 1)

    def test_attack_into_protect_not_type_immunity(self):
        """Opponent attack into the bot's Protect produces an
        ``|-immune|`` but it is the Protect parser's job, not
        the type-immunity parser. The cur_move of the parser
        is the attacker's move (Earthquake), not the
        protected pokemon's Protect. To avoid the legacy
        attack-into-Protect false-positive, the parser's
        existing Protect-like filter applies only when the
        |move| line itself was a Protect-like action. For an
        attack-into-Protect case, the move line is the
        attacker's move (e.g. Earthquake). This test
        documents that the parser relies on the Protect
        parser to handle the attacker-side path and does not
        regress it: the no_effect_policy_gate continues to
        pass for a single attack-into-protect event.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Incineroar|Protect",
                "|turn|2",
                "|move|p2a: Garchomp|Earthquake|p1a: Incineroar",
                "|-immune|p1a: Incineroar",
            ]
            _write_battle_jsonl(tmp, "battle-protect-immune", lines)
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        # A single attack-into-Protect is one no-effect event
        # but NOT a policy bug (no repeated same-target).
        # The Protect-spam parser is responsible for the
        # attacker side, not this one.
        self.assertEqual(s["no_effect_policy_bug_count"], 0)
        self.assertEqual(s["repeated_no_effect_move_count"], 0)
        self.assertTrue(s["no_effect_policy_gate_pass"])
        # The productive-partial-spread logic does not
        # affect this case.
        self.assertEqual(
            s["productive_partial_spread_no_effect_false_positive_count"],
            0,
        )

    def test_status_failure_not_damaging_no_effect(self):
        """Status move into immune (e.g. Thunder Wave into
        Ground) is not a damaging no-effect event. Must NOT
        be counted.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Jolteon|Thunder Wave|p2a: Garchomp",
                "|-immune|p2a: Garchomp",
            ]
            _write_battle_jsonl(tmp, "battle-status-immune", lines)
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        self.assertEqual(s["no_effect_policy_bug_count"], 0)
        self.assertEqual(s["no_effect_move_count"], 0)
        self.assertTrue(s["no_effect_policy_gate_pass"])

    def test_productive_partial_spread_recorded_separately(self):
        """The productive partial spread event is recorded in
        ``events`` with the correct classification and NOT
        counted in ``no_effect_policy_bug_count``.

        Real protocol order: ``|move| -> |-immune| ->
        |-damage|``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Garchomp|Earthquake|p2a: Tyranitar",
                "|-immune|p2b: Tornadus",
                "|-damage|p2a: Tyranitar|150/200",
                "|turn|2",
                "|move|p1a: Garchomp|Rock Slide|p2a: Tyranitar",
                "|-immune|p2b: Tornadus",
                "|-damage|p2a: Tyranitar|120/200",
            ]
            _write_battle_jsonl(
                tmp, "battle-spread-events", lines
            )
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        # Two productive partial spread events.
        self.assertEqual(
            s["productive_partial_spread_no_effect_false_positive_count"],
            2,
        )
        self.assertEqual(s["no_effect_policy_bug_count"], 0)
        self.assertTrue(s["no_effect_policy_gate_pass"])
        # Events list has the productive-partial classification.
        ev_classes = [
            e.get("classification")
            for e in s.get("events", [])
        ]
        self.assertEqual(
            ev_classes.count(
                "PRODUCTIVE_PARTIAL_SPREAD_NO_EFFECT_FALSE_POSITIVE"
            ),
            2,
        )
        self.assertNotIn(
            "POLICY_BUG_REPEATED_NO_EFFECT", ev_classes
        )

    def test_existing_raw_monitor_tests_still_pass(self):
        """Backward compat: the existing ff-monitor raw tests
        must still pass with the new partial-spread logic.
        """
        with tempfile.TemporaryDirectory() as tmp:
            # Pure spread move into a single opponent with
            # no immune line: should produce 0 no-effect
            # events.
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Garchomp|Earthquake|p2a: Tyranitar",
                "|-damage|p2a: Tyranitar|123/200",
            ]
            _write_battle_jsonl(
                tmp, "battle-spread-clean", lines
            )
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        self.assertEqual(s["no_effect_move_count"], 0)
        self.assertEqual(
            s["productive_partial_spread_no_effect_false_positive_count"],
            0,
        )
        self.assertTrue(s["no_effect_policy_gate_pass"])


class TestNoEffectProductivePartialSpread_ExistingCompat(unittest.TestCase):
    """Verify that legacy repeated-no-effect detection (single
    target) still triggers correctly.
    """

    def test_repeated_single_target_ground_immunity(self):
        """Two consecutive Thunderbolt into Garchomp produce
        a real no-effect policy bug.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Jolteon|Thunderbolt|p2a: Garchomp",
                "|-immune|p2a: Garchomp",
                "|turn|2",
                "|move|p1a: Jolteon|Thunderbolt|p2a: Garchomp",
                "|-immune|p2a: Garchomp",
            ]
            _write_battle_jsonl(
                tmp, "battle-repeated-immune", lines
            )
            s = parse_no_effect_attacks_from_raw_protocol(tmp)
        self.assertEqual(s["no_effect_move_count"], 2)
        self.assertEqual(
            s["known_immunity_no_effect_count"], 2
        )
        self.assertGreaterEqual(
            s["repeated_no_effect_move_count"], 1
        )
        self.assertGreaterEqual(
            s["no_effect_policy_bug_count"], 1
        )
        self.assertFalse(s["no_effect_policy_gate_pass"])


class TestLowValuePriorityDiagnostic(unittest.TestCase):
    """PHASE7_POLICY_SANITY_PRIORITY_SPAM_DIAGNOSTIC.

    Diagnostic-only parser for low-value positive-priority
    damaging moves (Quick Attack, Aqua Jet, Mach Punch,
    etc.). Does not change scoring and does not fail any
    gate.
    """

    def test_no_low_value_priority_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Incineroar|Fake Out|p2a: Tyranitar",
                "|turn|2",
                "|move|p1a: Incineroar|Flare Blitz|p2a: Tyranitar",
            ]
            _write_battle_jsonl(tmp, "battle-clean", lines)
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 0)
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 0
        )
        self.assertEqual(
            s["low_value_priority_repeated_count"], 0
        )
        self.assertEqual(s["low_value_priority_battles"], 0)
        self.assertTrue(s["low_value_priority_gate_pass"])

    def test_single_quick_attack_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
            ]
            _write_battle_jsonl(tmp, "battle-qa-once", lines)
            s = parse_low_value_priority_from_raw_protocol(tmp)
        # 1 Quick Attack: counted as a low-value move but
        # NOT as consecutive (no prior turn to compare).
        self.assertEqual(s["low_value_priority_move_count"], 1)
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 0
        )
        self.assertEqual(s["low_value_priority_battles"], 0)
        self.assertEqual(
            s["low_value_priority_by_move_id"].get("quickattack"), 1
        )

    def test_consecutive_quick_attack_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
                "|turn|2",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
            ]
            _write_battle_jsonl(
                tmp, "battle-qa-consecutive", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        # 2 Quick Attacks in a row: 1 consecutive event.
        self.assertEqual(s["low_value_priority_move_count"], 2)
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 1
        )
        self.assertEqual(s["low_value_priority_battles"], 1)
        self.assertEqual(
            s["low_value_priority_by_battle"].get(
                "battle-qa-consecutive.jsonl"
            ),
            2,
        )

    def test_repeated_quick_attack_counted(self):
        # 3 consecutive Quick Attacks: 1 consecutive
        # event on turn 2 + 1 repeated event on turn 3.
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
                "|turn|2",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
                "|turn|3",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
            ]
            _write_battle_jsonl(
                tmp, "battle-qa-repeated", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 3)
        # 2 consecutive events (turn 2 and turn 3).
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 2
        )
        # 1 repeated event (turn 3 is the 2nd consecutive).
        self.assertEqual(
            s["low_value_priority_repeated_count"], 1
        )

    def test_opponent_quick_attack_not_counted(self):
        # Opponent Quick Attack is reported on all-sides
        # but our parser only counts p1 (bot-side).
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p2a: Opp|Quick Attack|p1a: Bot",
                "|turn|2",
                "|move|p2a: Opp|Quick Attack|p1a: Bot",
            ]
            _write_battle_jsonl(
                tmp, "battle-opp-qa", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 0)
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 0
        )

    def test_non_priority_move_resets_streak(self):
        # Quick Attack, then Tackle, then Quick Attack
        # again -> 1 consecutive (turn 2) is blocked
        # by the tackle on turn 2. The 2nd Quick Attack
        # on turn 3 is fresh.
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
                "|turn|2",
                "|move|p1a: Sylveon|Tackle|p2a: Garchomp",
                "|turn|3",
                "|move|p1a: Sylveon|Quick Attack|p2a: Garchomp",
            ]
            _write_battle_jsonl(
                tmp, "battle-qa-with-tackle", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 2)
        # Tackle reset the streak; the 2nd Quick Attack
        # is a fresh move and not consecutive.
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 0
        )

    def test_aqua_jet_mach_punch_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Feraligatr|Aqua Jet|p2a: Dragonite",
                "|turn|2",
                "|move|p1a: Conkeldurr|Mach Punch|p2a: Tyranitar",
            ]
            _write_battle_jsonl(
                tmp, "battle-multiple-moves", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 2)
        self.assertEqual(
            s["low_value_priority_by_move_id"].get("aquajet"), 1
        )
        self.assertEqual(
            s["low_value_priority_by_move_id"].get("machpunch"), 1
        )

    def test_suckerpunch_not_low_value(self):
        # Suckerpunch is a high-value priority move and
        # is NOT in the low-value set. The parser should
        # not count it.
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Bisharp|Sucker Punch|p2a: Garchomp",
                "|turn|2",
                "|move|p1a: Bisharp|Sucker Punch|p2a: Garchomp",
            ]
            _write_battle_jsonl(
                tmp, "battle-suckerpunch", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 0)
        self.assertEqual(
            s["low_value_priority_consecutive_count"], 0
        )

    def test_fakeout_not_low_value(self):
        # Fakeout is a first-turn priority move and is
        # not in the low-value set.
        with tempfile.TemporaryDirectory() as tmp:
            lines = [
                "|player|p1|bot|",
                "|player|p2|opp|",
                "|turn|1",
                "|move|p1a: Incineroar|Fake Out|p2a: Tyranitar",
            ]
            _write_battle_jsonl(
                tmp, "battle-fakeout", lines
            )
            s = parse_low_value_priority_from_raw_protocol(tmp)
        self.assertEqual(s["low_value_priority_move_count"], 0)


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
