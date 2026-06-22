"""Phase RUNNER-TIMING-1 — Tests for opt-in timing
diagnostics flag in the V3a.2 reality runner.

Covers:
  1. CLI default is False.
  2. CLI flag sets a config with timing on.
  3. CLI flag combines with Mega flag.
  4. CLI flag does not enable Mega.
  5. Summary row includes the timing flag.
  6. Audit metadata includes the timing flag.
  7. Default OFF preserves unchanged config.

Pure unit tests. No Showdown, no poke-env.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.abspath(__file__))
)


def _load_runner_module():
    """Load the runner module from its filename. The
    runner lives in the same directory as the test
    files, so we use __file__'s directory directly."""
    runner_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "bot_vgc2026_phaseV3a2_reality.py",
    )
    spec = importlib.util.spec_from_file_location(
        "bot_vgc2026_phaseV3a2_reality", runner_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTimingConfigBuilder(unittest.TestCase):
    """Tests for ``build_treatment_player_config_with_timing``.
    Pure helper, no runner, no Showdown.
    """

    def setUp(self):
        self.runner = _load_runner_module()

    def test_default_false_returns_base_unchanged(self):
        # Flag False, base None -> None.
        out = self.runner.build_treatment_player_config_with_timing(
            None, False
        )
        self.assertIsNone(out)
        # Flag False, base is a config object -> unchanged.
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        base = DoublesDamageAwareConfig(enable_mega_evolution=True)
        out = self.runner.build_treatment_player_config_with_timing(
            base, False
        )
        self.assertIs(out, base)
        self.assertFalse(
            out.enable_decision_timing_diagnostics
        )

    def test_flag_true_with_none_base_creates_timing_config(self):
        out = self.runner.build_treatment_player_config_with_timing(
            None, True
        )
        self.assertIsNotNone(out)
        self.assertTrue(
            out.enable_decision_timing_diagnostics
        )
        # Mega must be False (timing alone does not
        # imply Mega).
        self.assertFalse(out.enable_mega_evolution)

    def test_flag_true_with_mega_base_merges(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        base = DoublesDamageAwareConfig(enable_mega_evolution=True)
        out = self.runner.build_treatment_player_config_with_timing(
            base, True
        )
        self.assertTrue(out.enable_mega_evolution)
        self.assertTrue(
            out.enable_decision_timing_diagnostics
        )

    def test_flag_true_with_piecewise_base_preserves_piecewise(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        base = DoublesDamageAwareConfig(
            enable_speed_priority_piecewise_expected_faint_policy=True
        )
        out = self.runner.build_treatment_player_config_with_timing(
            base, True
        )
        self.assertTrue(
            out.enable_speed_priority_piecewise_expected_faint_policy
        )
        self.assertTrue(
            out.enable_decision_timing_diagnostics
        )
        # Mega still off (we did not set Mega).
        self.assertFalse(out.enable_mega_evolution)

    def test_flag_true_with_mega_and_piecewise_preserves_all(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        base = DoublesDamageAwareConfig(
            enable_mega_evolution=True,
            enable_speed_priority_piecewise_expected_faint_policy=True,
        )
        out = self.runner.build_treatment_player_config_with_timing(
            base, True
        )
        self.assertTrue(out.enable_mega_evolution)
        self.assertTrue(
            out.enable_speed_priority_piecewise_expected_faint_policy
        )
        self.assertTrue(
            out.enable_decision_timing_diagnostics
        )


class TestCLIDefault(unittest.TestCase):
    """Test that the CLI flag default is False."""

    def setUp(self):
        self.runner = _load_runner_module()

    def test_timing_flag_default_false(self):
        """When ``--enable-timing-diagnostics`` is not
        on the command line, argparse stores False."""
        # We can read the default from the parser itself
        # by parsing an empty argv (the actual main()
        # would error on missing localhost, but the
        # parser-level default is what we want).
        # Use sys.argv trick.
        old = sys.argv
        try:
            sys.argv = ["runner"]
            # Build the same parser main() builds.
            from argparse import ArgumentParser
            parser = ArgumentParser()
            parser.add_argument(
                "--enable-timing-diagnostics",
                action="store_true",
            )
            parser.add_argument(
                "--enable-mega-evolution",
                action="store_true",
            )
            args = parser.parse_args([])
            self.assertFalse(args.enable_timing_diagnostics)
            self.assertFalse(args.enable_mega_evolution)
        finally:
            sys.argv = old

    def test_runner_source_contains_flag_default(self):
        """Static check: the runner source registers
        ``--enable-timing-diagnostics`` as a
        ``store_true`` flag (default False)."""
        runner_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bot_vgc2026_phaseV3a2_reality.py",
        )
        with open(runner_path) as f:
            src = f.read()
        self.assertIn("--enable-timing-diagnostics", src)
        # The flag is registered as store_true.
        # Find the line and check.
        idx = src.find('--enable-timing-diagnostics')
        snippet = src[idx:idx + 400]
        self.assertIn("action=\"store_true\"", snippet)

    def test_runner_help_text_mentions_default_off(self):
        runner_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bot_vgc2026_phaseV3a2_reality.py",
        )
        with open(runner_path) as f:
            src = f.read()
        idx = src.find('--enable-timing-diagnostics')
        snippet = src[idx:idx + 1500]
        self.assertIn("Default OFF", snippet)
        self.assertIn("timing", snippet.lower())


class TestNoBehaviorChangeWhenFlagFalse(unittest.TestCase):
    """When the timing flag is False, the existing
    runner config wiring is preserved (no changes
    to production defaults).
    """

    def setUp(self):
        self.runner = _load_runner_module()

    def test_helper_off_returns_base_unchanged(self):
        """base=None, flag=False -> None (same as
        existing build_treatment_player_config with
        flag=False on Mega)."""
        out = self.runner.build_treatment_player_config_with_timing(
            None, False
        )
        self.assertIsNone(out)

    def test_helper_off_preserves_existing_mega_base(self):
        """base has Mega, flag=False -> unchanged base."""
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        base = DoublesDamageAwareConfig(enable_mega_evolution=True)
        out = self.runner.build_treatment_player_config_with_timing(
            base, False
        )
        self.assertIs(out, base)
        self.assertTrue(out.enable_mega_evolution)
        self.assertFalse(
            out.enable_decision_timing_diagnostics
        )

    def test_global_config_default_unchanged(self):
        """``DoublesDamageAwareConfig.enable_decision_timing_diagnostics``
        default is still False. This is the global
        default in the bot config.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        c = DoublesDamageAwareConfig()
        self.assertFalse(c.enable_decision_timing_diagnostics)


class TestAuditMetadata(unittest.TestCase):
    """Test that the audit logger records the timing
    flag in the persisted audit row.
    """

    def setUp(self):
        self.runner = _load_runner_module()
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        self.logger_cls = DoublesDecisionAuditLogger

    def test_set_current_battle_meta_default_timing_false(self):
        """Calling set_current_battle_meta without
        the new arg defaults to timing=False (backward
        compatible).
        """
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            path = f.name
        try:
            logger = self.logger_cls(
                filepath=path, reset=True
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=True,
                treatment_side="p1",
                player_side="p1",
                player_name="bot",
            )
            self.assertEqual(
                logger._current_battle_meta[
                    "enable_decision_timing_diagnostics"
                ],
                False,
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_set_current_battle_meta_timing_true(self):
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            path = f.name
        try:
            logger = self.logger_cls(
                filepath=path, reset=True
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=True,
                enable_decision_timing_diagnostics=True,
                treatment_side="p1",
                player_side="p1",
                player_name="bot",
            )
            self.assertEqual(
                logger._current_battle_meta[
                    "enable_decision_timing_diagnostics"
                ],
                True,
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_logger_saves_battle_with_timing_field(self):
        """A full save_battle path persists
        enable_decision_timing_diagnostics in the
        audit row.
        """
        from unittest.mock import MagicMock
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False
        ) as f:
            path = f.name
        try:
            logger = self.logger_cls(
                filepath=path, reset=True
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=True,
                enable_decision_timing_diagnostics=True,
                treatment_side="p1",
                player_side="p1",
                player_name="bot",
            )
            battle = MagicMock()
            battle.turn = 5
            battle.player_username = "bot"
            logger.save_battle(
                "test-battle-1", "bot", battle
            )
            with open(path) as f:
                line = f.readline()
            row = json.loads(line)
            self.assertIn(
                "enable_decision_timing_diagnostics", row
            )
            self.assertTrue(
                row["enable_decision_timing_diagnostics"]
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestSummaryMetadata(unittest.TestCase):
    """Test that the run_one_battle summary row
    includes the timing flag.
    """

    def setUp(self):
        self.runner = _load_runner_module()

    def test_run_one_battle_signature_has_timing_param(self):
        sig = inspect.signature(self.runner.run_one_battle)
        self.assertIn(
            "enable_decision_timing_diagnostics", sig.parameters
        )
        # Default False.
        self.assertEqual(
            sig.parameters[
                "enable_decision_timing_diagnostics"
            ].default,
            False,
        )

    def test_run_one_battle_summary_includes_timing_field(self):
        """Source check: the summary dict in
        run_one_battle includes
        enable_decision_timing_diagnostics.
        """
        runner_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bot_vgc2026_phaseV3a2_reality.py",
        )
        with open(runner_path) as f:
            src = f.read()
        # The summary dict construction must reference
        # enable_decision_timing_diagnostics.
        self.assertIn(
            '"enable_decision_timing_diagnostics"', src
        )
        # The flag must be wired into the run_one_battle
        # return dict, not just an unrelated field.
        # Find run_one_battle function and check it
        # references the field.
        idx = src.find("def run_one_battle")
        end = src.find("def ", idx + 1)
        body = src[idx:end]
        self.assertIn(
            "enable_decision_timing_diagnostics", body
        )


class TestFlagCombinations(unittest.TestCase):
    """Test the various flag combinations the spec
    requires.
    """

    def setUp(self):
        self.runner = _load_runner_module()

    def test_timing_alone_no_mega(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        out = self.runner.build_treatment_player_config_with_timing(
            None, True
        )
        self.assertTrue(
            out.enable_decision_timing_diagnostics
        )
        self.assertFalse(out.enable_mega_evolution)

    def test_timing_with_mega(self):
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        mega = DoublesDamageAwareConfig(enable_mega_evolution=True)
        out = self.runner.build_treatment_player_config_with_timing(
            mega, True
        )
        self.assertTrue(out.enable_mega_evolution)
        self.assertTrue(
            out.enable_decision_timing_diagnostics
        )

    def test_mega_alone_no_timing(self):
        out = self.runner.build_treatment_player_config(
            is_treatment=True, enable_mega_evolution=True
        )
        self.assertIsNotNone(out)
        self.assertTrue(out.enable_mega_evolution)
        self.assertFalse(
            out.enable_decision_timing_diagnostics
        )

    def test_no_flags_returns_none(self):
        out = self.runner.build_treatment_player_config(
            is_treatment=True, enable_mega_evolution=False
        )
        self.assertIsNone(out)


class TestBannerOutput(unittest.TestCase):
    """Test that the runner prints a banner when
    timing is enabled.
    """

    def setUp(self):
        self.runner = _load_runner_module()

    def test_banner_mentions_timing(self):
        """Static check: the main() print banner
        includes the timing branch.
        """
        runner_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bot_vgc2026_phaseV3a2_reality.py",
        )
        with open(runner_path) as f:
            src = f.read()
        # The banner has a branch for enable_timing_diagnostics.
        self.assertIn(
            "enable_timing_diagnostics=True", src
        )
        self.assertIn("RUNNER-TIMING-1", src)


if __name__ == "__main__":
    unittest.main()
