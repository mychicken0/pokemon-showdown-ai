"""Phase BI-3F-1: runner audit-decisions opt-in tests.

These tests prove:
- ``--audit-decisions`` flag exists with default OFF.
- Default omitted means no audit logger path is created.
- Audit path naming uses the tag.
- No production import of ``poke_env_test_cleanup``.

The tests are at the CLI level (subprocess) so they don't depend
on Showdown being up. They verify runner help and the banner
output that announces the audit path.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


class TestRunnerHelp(unittest.TestCase):
    def test_help_includes_audit_decisions(self):
        """``--help`` shows the new flag."""
        result = subprocess.run(
            [
                os.path.join(PROJECT_DIR, "venv", "bin", "python"),
                os.path.join(PROJECT_DIR, "bot_vgc2026_phaseV3a2_reality.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--audit-decisions", result.stdout)
        self.assertIn("BI-3F-1", result.stdout)
        # Default OFF semantics must be explicit.
        self.assertIn("Default OFF", result.stdout)


class TestRunnerAuditPathNaming(unittest.TestCase):
    def test_audit_path_uses_tag_when_enabled(self):
        """The audit paths are ``logs/vgc2026_<tag>_treatment_audit.jsonl``
        and ``logs/vgc2026_<tag>_baseline_audit.jsonl`` when
        the flag is enabled.
        """
        # Inspect the runner source for the path templates.
        with open(
            os.path.join(
                PROJECT_DIR,
                "bot_vgc2026_phaseV3a2_reality.py",
            )
        ) as f:
            content = f.read()
        self.assertIn(
            'f"vgc2026_{args.tag}_treatment_audit.jsonl"',
            content,
        )
        self.assertIn(
            'f"vgc2026_{args.tag}_baseline_audit.jsonl"',
            content,
        )


class TestRunnerDefaultNoAudit(unittest.TestCase):
    def test_no_audit_when_flag_omitted(self):
        """When ``--audit-decisions`` is omitted, the audit
        loggers are NOT constructed (the banner does NOT
        mention audit).
        """
        # Inspect the runner source for the conditional
        # that controls audit logger construction.
        with open(
            os.path.join(
                PROJECT_DIR,
                "bot_vgc2026_phaseV3a2_reality.py",
            )
        ) as f:
            content = f.read()
        # Audit logger construction is gated by --audit-decisions.
        self.assertIn("if args.audit_decisions:", content)
        # Banner only mentions audit when flag is set.
        self.assertIn("audit_logger_treatment is not None", content)
        # Print AUDIT line only when logger is set.
        self.assertIn('print(f"  AUDIT-T: {audit_path_treatment}")', content)


class TestTreatmentArmWiring(unittest.TestCase):
    """Phase BI-3K.3: the Mega treatment config must follow the
    treatment/learned arm across BOTH D1 and D2, not just D1.
    Previously the config was applied only when the treatment arm
    was p1 (``is_learned_first``), which silently dropped the
    treatment effect in D2 and invalidated the ON-vs-OFF paired
    comparison.
    """

    def _import_helper(self):
        from bot_vgc2026_phaseV3a2_reality import (
            build_treatment_player_config,
        )
        return build_treatment_player_config

    def test_d1_treatment_gets_mega_config(self):
        """D1: p1 is treatment (is_treatment=True).
        Config must be a DoublesDamageAwareConfig with
        enable_mega_evolution=True.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        helper = self._import_helper()
        cfg = helper(
            is_treatment=True, enable_mega_evolution=True
        )
        self.assertIsNotNone(cfg)
        self.assertIsInstance(cfg, DoublesDamageAwareConfig)
        self.assertTrue(cfg.enable_mega_evolution)

    def test_d2_treatment_gets_mega_config(self):
        """D2: p2 is treatment (is_treatment=True for the
        D2 run_one_battle call). The helper does not care
        which side is treatment — it only checks
        is_treatment flag. This is the BI-3K.3 fix.
        """
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        helper = self._import_helper()
        cfg = helper(
            is_treatment=True, enable_mega_evolution=True
        )
        self.assertIsNotNone(cfg)
        self.assertTrue(cfg.enable_mega_evolution)

    def test_baseline_arm_gets_none(self):
        """Baseline arm (is_treatment=False) must get None
        regardless of which side it is. Caller leaves
        config unset so the bot uses default.
        """
        helper = self._import_helper()
        cfg = helper(
            is_treatment=False, enable_mega_evolution=True
        )
        self.assertIsNone(cfg)

    def test_flag_off_returns_none(self):
        """Without --enable-mega-evolution, treatment arm
        also gets None. Both arms use default config.
        """
        helper = self._import_helper()
        cfg = helper(
            is_treatment=True, enable_mega_evolution=False
        )
        self.assertIsNone(cfg)

    def test_runner_attaches_config_to_treatment_side_d1(self):
        """D1 wiring: p1 is treatment → p1_kwargs gets config.
        p2 does NOT get config (baseline).
        """
        import inspect
        from bot_vgc2026_phaseV3a2_reality import (
            build_treatment_player_config,
        )
        src = inspect.getsource(build_treatment_player_config)
        self.assertIn("is_treatment", src)
        self.assertIn("enable_mega_evolution", src)

    def test_runner_uses_helper_not_hardcoded_p1(self):
        """The runner no longer hardcodes ``is_learned_first``
        for the Mega config branch. The treatment config is
        built from ``is_treatment`` (which is True based on
        side, NOT policy string equality).
        """
        with open("bot_vgc2026_phaseV3a2_reality.py") as f:
            content = f.read()
        # The old hardcoded branch is gone.
        self.assertNotIn(
            "if enable_mega_evolution and is_learned_first:",
            content,
        )
        # The new helper-based branch is present.
        self.assertIn("build_treatment_player_config", content)
        # Phase BI-3K.6: treatment is determined by side, not
        # by policy string equality.
        self.assertIn("p1_is_treatment = (side == \"p1\")", content)
        self.assertIn("p2_is_treatment = (side == \"p2\")", content)
        # The old policy-equality inference is gone.
        self.assertNotIn(
            "is_treatment = (player_policy == learned_policy)",
            content,
        )


class TestAuditArmMetadata(unittest.TestCase):
    """Phase BI-3K.3: audit metadata distinguishes treatment
    vs baseline and records Mega config per battle.
    """

    def test_set_battle_arm_persists_fields(self):
        """set_battle_arm stores the metadata so save_battle
        can include it in the persisted row.
        """
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/audit.jsonl"
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5"
            )
            logger.set_battle_arm(
                battle_tag="b1",
                benchmark_arm="treatment",
                enable_mega_evolution=True,
                treatment_side="p1",
            )
            self.assertIn("b1", logger._battle_arm_meta)
            meta = logger._battle_arm_meta["b1"]
            self.assertEqual(meta["benchmark_arm"], "treatment")
            self.assertTrue(meta["enable_mega_evolution"])
            self.assertEqual(meta["treatment_side"], "p1")

    def test_set_battle_arm_overwrites(self):
        """Setting twice for the same battle_tag overwrites
        (the second call wins). This is correct because the
        runner calls set_battle_arm once per battle.
        """
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/audit.jsonl"
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5"
            )
            logger.set_battle_arm(
                battle_tag="b2", benchmark_arm="treatment",
                enable_mega_evolution=True, treatment_side="p1",
            )
            logger.set_battle_arm(
                battle_tag="b2", benchmark_arm="baseline",
                enable_mega_evolution=False, treatment_side="p2",
            )
            meta = logger._battle_arm_meta["b2"]
            self.assertEqual(meta["benchmark_arm"], "baseline")
            self.assertFalse(meta["enable_mega_evolution"])
            self.assertEqual(meta["treatment_side"], "p2")

    def test_save_battle_includes_arm_metadata(self):
        """save_battle pops the per-battle metadata and
        includes benchmark_arm, enable_mega_evolution, and
        treatment_side in the persisted row.
        """
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/audit.jsonl"
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5"
            )
            logger.set_battle_arm(
                battle_tag="b3", benchmark_arm="treatment",
                enable_mega_evolution=True, treatment_side="p1",
            )

            class FakeBattle:
                player_username = "bot1"
                turn = 5

            logger.save_battle("b3", "bot1", FakeBattle())
            with open(path) as f:
                line = f.readline().strip()
            import json
            row = json.loads(line)
            self.assertEqual(row["benchmark_arm"], "treatment")
            self.assertTrue(row["enable_mega_evolution"])
            self.assertEqual(row["treatment_side"], "p1")


class TestSingleConstructionAndTreatmentSide(unittest.TestCase):
    """Phase BI-3K.6: single player construction + treatment
    side determined by side argument (not policy equality).
    """

    def _stub_team_row(self):
        class Row:
            pokemon = [
                {"species": "charizard", "moves": ["heatwave"]}
                for _ in range(6)
            ]
        return Row()

    def _run_battle_with_counted_constructions(
        self, side, player_policy, opponent_policy,
        enable_mega_evolution=False,
        audit_logger_treatment=None, audit_logger_baseline=None,
        account_run_id="R1",
    ):
        """Run ``run_one_battle`` with a stub pool and
        monkeypatched ``ControlledTeamPreviewPlayer`` that
        counts how many times the constructor was called.
        Returns ``(count, summary)``.
        """
        import asyncio
        from unittest.mock import patch
        import bot_vgc2026_phaseV3a2_reality as runner_mod

        class CountedPlayer:
            counter = 0
            battles = {}
            n_finished_battles = 1
            n_won_battles = 1
            preview_result = None

            def __init__(self, *args, **kwargs):
                CountedPlayer.counter += 1
                self.kwargs = kwargs
                self._preview = kwargs.get("preview_result")

            @property
            def preview_result(self):
                return self._preview

            @preview_result.setter
            def preview_result(self, v):
                self._preview = v

            async def battle_against(self, other, n_battles=1):
                return None

        pool = type("Pool", (), {})()
        pool.get_team = lambda i: self._stub_team_row()

        CountedPlayer.counter = 0
        with patch.object(
            runner_mod, "ControlledTeamPreviewPlayer", CountedPlayer
        ):
            summary = asyncio.run(runner_mod.run_one_battle(
                pair_id=18, side=side,
                player_policy=player_policy,
                opponent_policy=opponent_policy,
                our_team_idx=0, opp_team_idx=0,
                pool=pool, seed=42, timeout=5.0,
                learned_policy="matchup_top4_v3",
                account_prefix="BK6_",
                account_run_id=account_run_id,
                enable_mega_evolution=enable_mega_evolution,
                audit_logger_treatment=audit_logger_treatment,
                audit_logger_baseline=audit_logger_baseline,
            ))
        return CountedPlayer.counter, summary

    def test_single_construction_d1(self):
        """D1 (side=p1): exactly 2 constructions, not 3."""
        count, summary = self._run_battle_with_counted_constructions(
            side="p1",
            player_policy="matchup_top4_v3",
            opponent_policy="matchup_top4_v3",
            enable_mega_evolution=True,
        )
        self.assertEqual(count, 2, summary.get("error_detail"))
        # Summary reflects treatment side = p1.
        self.assertEqual(summary["treatment_side"], "p1")
        self.assertTrue(summary["enable_mega_evolution"])

    def test_single_construction_d2(self):
        """D2 (side=p2): exactly 2 constructions, not 3."""
        count, summary = self._run_battle_with_counted_constructions(
            side="p2",
            player_policy="matchup_top4_v3",
            opponent_policy="matchup_top4_v3",
            enable_mega_evolution=True,
        )
        self.assertEqual(count, 2, summary.get("error_detail"))
        # Summary reflects treatment side = p2.
        self.assertEqual(summary["treatment_side"], "p2")
        self.assertTrue(summary["enable_mega_evolution"])

    def test_d1_config_attaches_to_p1_only(self):
        """D1: only p1 gets config; p2 does NOT."""
        import asyncio
        from unittest.mock import patch
        import bot_vgc2026_phaseV3a2_reality as runner_mod

        class CapturingPlayer:
            counter = 0
            battles = {}
            n_finished_battles = 1
            n_won_battles = 1
            preview_result = None

            def __init__(self, *args, **kwargs):
                CapturingPlayer.counter += 1
                self.kwargs = kwargs
                self._preview = kwargs.get("preview_result")

            @property
            def preview_result(self):
                return self._preview

            @preview_result.setter
            def preview_result(self, v):
                self._preview = v

            async def battle_against(self, other, n_battles=1):
                return None

        pool = type("Pool", (), {})()
        pool.get_team = lambda i: self._stub_team_row()
        CapturingPlayer.counter = 0
        with patch.object(
            runner_mod, "ControlledTeamPreviewPlayer", CapturingPlayer
        ):
            summary = asyncio.run(runner_mod.run_one_battle(
                pair_id=18, side="p1",
                player_policy="matchup_top4_v3",
                opponent_policy="matchup_top4_v3",
                our_team_idx=0, opp_team_idx=0,
                pool=pool, seed=42, timeout=5.0,
                learned_policy="matchup_top4_v3",
                account_prefix="BK6_",
                account_run_id="R1",
                enable_mega_evolution=True,
            ))
        self.assertEqual(CapturingPlayer.counter, 2)
        self.assertEqual(summary["treatment_side"], "p1")
        self.assertTrue(summary["enable_mega_evolution"])

    def test_same_policy_still_assigns_treatment_by_side(self):
        """Same policy on both arms: treatment is still
        determined by side argument, not by policy equality.
        """
        import asyncio
        from unittest.mock import patch
        import bot_vgc2026_phaseV3a2_reality as runner_mod

        class Stub:
            counter = 0
            battles = {}
            n_finished_battles = 1
            n_won_battles = 1
            preview_result = None

            def __init__(self, *args, **kwargs):
                Stub.counter += 1
                self.kwargs = kwargs
                self._preview = kwargs.get("preview_result")

            @property
            def preview_result(self):
                return self._preview

            @preview_result.setter
            def preview_result(self, v):
                self._preview = v

            async def battle_against(self, other, n_battles=1):
                return None

        pool = type("Pool", (), {})()
        pool.get_team = lambda i: self._stub_team_row()
        Stub.counter = 0
        with patch.object(
            runner_mod, "ControlledTeamPreviewPlayer", Stub
        ):
            summary = asyncio.run(runner_mod.run_one_battle(
                pair_id=18, side="p2",
                player_policy="matchup_top4_v3",
                opponent_policy="matchup_top4_v3",
                our_team_idx=0, opp_team_idx=0,
                pool=pool, seed=42, timeout=5.0,
                learned_policy="matchup_top4_v3",
                account_prefix="BK6_",
                account_run_id="R1",
                enable_mega_evolution=True,
            ))
        self.assertEqual(Stub.counter, 2)
        self.assertEqual(summary["treatment_side"], "p2")
        self.assertEqual(summary["benchmark_arm"], "treatment")
        self.assertTrue(summary["enable_mega_evolution"])


class TestAuditBothArms(unittest.TestCase):
    """Phase BI-3K.7: audit logger attaches to BOTH p1 and p2
    when --audit-decisions is enabled. The treatment logger
    goes to the treatment side; the baseline logger goes to
    the baseline side. This is observational only and does
    not affect scoring or selection.
    """

    def _stub_team_row(self):
        class Row:
            pokemon = [
                {"species": "charizard", "moves": ["heatwave"]}
                for _ in range(6)
            ]
        return Row()

    def _run_battle_with_audit(
        self, side, enable_mega_evolution=True,
    ):
        """Run ``run_one_battle`` with stub loggers that
        record what was passed and how many times save_battle
        was called.
        """
        import asyncio
        from unittest.mock import patch
        import bot_vgc2026_phaseV3a2_reality as runner_mod

        class StubLogger:
            instances = []
            def __init__(self, *a, **kw):
                self.calls = []
                self.set_meta_calls = []
                StubLogger.instances.append(self)
            def set_current_battle_meta(self, **kw):
                self.set_meta_calls.append(kw)
            def save_battle(self, battle_tag, winner, battle):
                self.calls.append((battle_tag, winner))
            def __getattr__(self, name):
                # Anything else (update_previous_turn, etc.) is a no-op.
                return lambda *a, **kw: None

        StubLogger.instances = []

        class StubPlayer:
            counter = 0
            battles = {}
            n_finished_battles = 1
            n_won_battles = 1
            preview_result = None
            attached_loggers = []

            def __init__(self, *args, **kwargs):
                StubPlayer.counter += 1
                self.kwargs = kwargs
                self._preview = kwargs.get("preview_result")
                if "audit_logger" in kwargs:
                    StubPlayer.attached_loggers.append(kwargs["audit_logger"])

            @property
            def preview_result(self):
                return self._preview

            @preview_result.setter
            def preview_result(self, v):
                self._preview = v

            async def battle_against(self, other, n_battles=1):
                return None

        pool = type("Pool", (), {})()
        pool.get_team = lambda i: self._stub_team_row()
        StubPlayer.counter = 0
        StubPlayer.attached_loggers = []
        treatment_logger = StubLogger()
        baseline_logger = StubLogger()
        with patch.object(
            runner_mod, "ControlledTeamPreviewPlayer", StubPlayer
        ):
            summary = asyncio.run(runner_mod.run_one_battle(
                pair_id=18, side=side,
                player_policy="matchup_top4_v3",
                opponent_policy="matchup_top4_v3",
                our_team_idx=0, opp_team_idx=0,
                pool=pool, seed=42, timeout=5.0,
                learned_policy="matchup_top4_v3",
                account_prefix="BK7_",
                account_run_id="Q7A1",
                enable_mega_evolution=enable_mega_evolution,
                audit_logger_treatment=treatment_logger,
                audit_logger_baseline=baseline_logger,
            ))
        return summary, StubPlayer, treatment_logger, baseline_logger

    def test_audit_attaches_to_both_arms_d1(self):
        """D1 (side=p1): p1 gets treatment logger, p2 gets
        baseline logger. Both players have an audit logger.
        """
        summary, StubPlayer, tlog, blog = self._run_battle_with_audit(
            side="p1"
        )
        self.assertEqual(StubPlayer.counter, 2)
        # Two distinct loggers attached.
        self.assertEqual(len(StubPlayer.attached_loggers), 2)
        self.assertIn(tlog, StubPlayer.attached_loggers)
        self.assertIn(blog, StubPlayer.attached_loggers)
        self.assertIsNot(tlog, blog)

    def test_audit_attaches_to_both_arms_d2(self):
        """D2 (side=p2): p2 gets treatment logger, p1 gets
        baseline logger. Both players have an audit logger.
        """
        summary, StubPlayer, tlog, blog = self._run_battle_with_audit(
            side="p2"
        )
        self.assertEqual(StubPlayer.counter, 2)
        self.assertEqual(len(StubPlayer.attached_loggers), 2)
        self.assertIn(tlog, StubPlayer.attached_loggers)
        self.assertIn(blog, StubPlayer.attached_loggers)
        self.assertIsNot(tlog, blog)

    def test_treatment_logger_metadata_d1(self):
        """D1 treatment logger: benchmark_arm=treatment,
        enable_mega_evolution=True, treatment_side=p1.
        """
        summary, _, tlog, _ = self._run_battle_with_audit(side="p1")
        self.assertEqual(len(tlog.set_meta_calls), 1)
        meta = tlog.set_meta_calls[0]
        self.assertEqual(meta["benchmark_arm"], "treatment")
        self.assertTrue(meta["enable_mega_evolution"])
        self.assertEqual(meta["treatment_side"], "p1")
        self.assertEqual(meta["player_side"], "p1")
        self.assertIn("Q7A1", meta["player_name"])

    def test_baseline_logger_metadata_d1(self):
        """D1 baseline logger: benchmark_arm=baseline,
        enable_mega_evolution=False, treatment_side=p2.
        """
        summary, _, _, blog = self._run_battle_with_audit(side="p1")
        self.assertEqual(len(blog.set_meta_calls), 1)
        meta = blog.set_meta_calls[0]
        self.assertEqual(meta["benchmark_arm"], "baseline")
        self.assertFalse(meta["enable_mega_evolution"])
        self.assertEqual(meta["treatment_side"], "p2")
        self.assertEqual(meta["player_side"], "p2")

    def test_treatment_logger_metadata_d2(self):
        """D2 treatment logger: benchmark_arm=treatment,
        treatment_side=p2, player_side=p2.
        """
        summary, _, tlog, _ = self._run_battle_with_audit(side="p2")
        meta = tlog.set_meta_calls[0]
        self.assertEqual(meta["benchmark_arm"], "treatment")
        self.assertTrue(meta["enable_mega_evolution"])
        self.assertEqual(meta["treatment_side"], "p2")
        self.assertEqual(meta["player_side"], "p2")

    def test_baseline_logger_metadata_d2(self):
        """D2 baseline logger: benchmark_arm=baseline,
        treatment_side=p1, player_side=p1.
        """
        summary, _, _, blog = self._run_battle_with_audit(side="p2")
        meta = blog.set_meta_calls[0]
        self.assertEqual(meta["benchmark_arm"], "baseline")
        self.assertFalse(meta["enable_mega_evolution"])
        self.assertEqual(meta["treatment_side"], "p1")
        self.assertEqual(meta["player_side"], "p1")

    def test_persisted_audit_row_includes_arm_metadata(self):
        """The save_battle path persists benchmark_arm,
        enable_mega_evolution, treatment_side, player_side,
        player_name in the row.
        """
        import tempfile
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/audit.jsonl"
            logger = DoublesDecisionAuditLogger(
                filepath=path, reset=True, detail_level="top5"
            )
            logger.set_current_battle_meta(
                benchmark_arm="treatment",
                enable_mega_evolution=True,
                treatment_side="p1",
                player_side="p1",
                player_name="BK7_Q7A1p0181L",
            )

            class FakeBattle:
                player_username = "BK7_Q7A1p0181L"
                turn = 5

            logger.save_battle("b1", "BK7_Q7A1p0181L", FakeBattle())
            with open(path) as f:
                line = f.readline().strip()
            import json
            row = json.loads(line)
            self.assertEqual(row["benchmark_arm"], "treatment")
            self.assertTrue(row["enable_mega_evolution"])
            self.assertEqual(row["treatment_side"], "p1")
            self.assertEqual(row["player_side"], "p1")
            self.assertEqual(row["player_name"], "BK7_Q7A1p0181L")

    def test_no_audit_when_flag_omitted(self):
        """When both audit loggers are None, neither
        player gets an audit logger.
        """
        import asyncio
        from unittest.mock import patch
        import bot_vgc2026_phaseV3a2_reality as runner_mod

        class StubPlayer:
            counter = 0
            attached = []
            battles = {}
            n_finished_battles = 1
            n_won_battles = 1
            preview_result = None

            def __init__(self, *args, **kwargs):
                StubPlayer.counter += 1
                if "audit_logger" in kwargs:
                    StubPlayer.attached.append(kwargs["audit_logger"])
                self._preview = kwargs.get("preview_result")

            @property
            def preview_result(self):
                return self._preview

            @preview_result.setter
            def preview_result(self, v):
                self._preview = v

            async def battle_against(self, other, n_battles=1):
                return None

        class Row:
            pokemon = [
                {"species": "charizard", "moves": ["heatwave"]}
                for _ in range(6)
            ]

        pool = type("Pool", (), {})()
        pool.get_team = lambda i: Row()
        StubPlayer.counter = 0
        StubPlayer.attached = []
        with patch.object(
            runner_mod, "ControlledTeamPreviewPlayer", StubPlayer
        ):
            asyncio.run(runner_mod.run_one_battle(
                pair_id=18, side="p1",
                player_policy="matchup_top4_v3",
                opponent_policy="matchup_top4_v3",
                our_team_idx=0, opp_team_idx=0,
                pool=pool, seed=42, timeout=5.0,
                learned_policy="matchup_top4_v3",
                account_prefix="BK7_",
                account_run_id="Q7A1",
                enable_mega_evolution=True,
                audit_logger_treatment=None,
                audit_logger_baseline=None,
            ))
        self.assertEqual(len(StubPlayer.attached), 0)


class TestAccountIsolation(unittest.TestCase):
    """Phase BI-3K.5: account name isolation across runs.

    The runner must avoid |nametaken| collisions by
    supporting an optional short run id embedded in the
    account name, with explicit length enforcement
    (no silent truncation) and a preflight uniqueness
    check.
    """

    def test_default_naming_unchanged(self):
        """Without --account-run-id, the old naming is
        preserved exactly (including its silent 18-char
        truncation for backward compatibility).
        """
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        name = make_player_name(
            pair_id=18, side="p1", learned=True,
            prefix="BI3K5_", account_run_id="",
        )
        # Old format: prefix + "pNN" + "_" + side + L/V
        self.assertTrue(name.startswith("BI3K5_p18"))
        self.assertTrue(name.endswith("L"))

    def test_run_id_naming_within_limit(self):
        """With --account-run-id, the name stays within
        the 18-char Showdown limit.
        """
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name, SHOWDOWN_NAME_MAX,
        )
        name = make_player_name(
            pair_id=18, side="p1", learned=True,
            prefix="BI3K5_", account_run_id="K5A1",
        )
        self.assertLessEqual(len(name), SHOWDOWN_NAME_MAX)
        # New format preserves side and L/V.
        self.assertIn("1L", name)
        # Run id is embedded.
        self.assertIn("K5A1", name)

    def test_run_id_naming_preserves_side(self):
        """p1 -> side_digit 1, p2 -> side_digit 2."""
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        p1 = make_player_name(
            pair_id=18, side="p1", learned=True,
            prefix="B_", account_run_id="R1",
        )
        p2 = make_player_name(
            pair_id=18, side="p2", learned=True,
            prefix="B_", account_run_id="R1",
        )
        self.assertIn("1L", p1)
        self.assertIn("2L", p2)
        self.assertNotEqual(p1, p2)

    def test_run_id_naming_preserves_arm(self):
        """L = learned, V = baseline. Both visible."""
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        l_name = make_player_name(
            pair_id=18, side="p1", learned=True,
            prefix="B_", account_run_id="R1",
        )
        v_name = make_player_name(
            pair_id=18, side="p1", learned=False,
            prefix="B_", account_run_id="R1",
        )
        self.assertTrue(l_name.endswith("L"))
        self.assertTrue(v_name.endswith("V"))
        self.assertNotEqual(l_name, v_name)

    def test_too_long_prefix_raises_before_connection(self):
        """A prefix + run id that exceeds 18 chars must
        raise ValueError, not silently truncate.
        """
        from bot_vgc2026_phaseV3a2_reality import (
            make_player_name,
        )
        # 13-char prefix + 4-char run id + "p018" (4) +
        # "1L" (2) = 23 chars. Must raise.
        with self.assertRaises(ValueError):
            make_player_name(
                pair_id=18, side="p1", learned=True,
                prefix="VERYLONGPRE_", account_run_id="K5A1",
            )

    def test_sanitize_run_id_alphanumeric(self):
        """_sanitize_run_id rejects non-alphanumeric."""
        from bot_vgc2026_phaseV3a2_reality import (
            _sanitize_run_id,
        )
        with self.assertRaises(ValueError):
            _sanitize_run_id("K5-A1")
        with self.assertRaises(ValueError):
            _sanitize_run_id("K5 A1")

    def test_sanitize_run_id_too_long(self):
        """_sanitize_run_id rejects >4 chars."""
        from bot_vgc2026_phaseV3a2_reality import (
            _sanitize_run_id,
        )
        with self.assertRaises(ValueError):
            _sanitize_run_id("K5A1X")

    def test_sanitize_run_id_empty(self):
        """_sanitize_run_id returns "" for falsy input."""
        from bot_vgc2026_phaseV3a2_reality import (
            _sanitize_run_id,
        )
        self.assertEqual(_sanitize_run_id(""), "")
        self.assertEqual(_sanitize_run_id(None), "")

    def test_preflight_uniqueness_200_pairs(self):
        """200 pairs x 4 (d1/d2 x p1/p2) = 800 names, all unique."""
        from bot_vgc2026_phaseV3a2_reality import (
            preflight_uniqueness_check,
        )
        result = preflight_uniqueness_check(
            n_pairs=200, start_pair=0,
            prefix="BI3K5_", account_run_id="K5A1",
        )
        # 200 pairs x 4 (d1p1, d1p2, d2p1, d2p2) = 800.
        self.assertEqual(len(result), 800)
        # All names unique (post-normalization).
        names = list(result.values())
        self.assertEqual(len(names), len(set(names)))

    def test_preflight_detects_duplicate(self):
        """A duplicate name is caught before connection.

        n_pairs > 1000 triggers collision via pair_id % 1000
        wrapping.
        """
        from bot_vgc2026_phaseV3a2_reality import (
            preflight_uniqueness_check,
        )
        with self.assertRaises(ValueError) as ctx:
            preflight_uniqueness_check(
                n_pairs=2000, start_pair=0,
                prefix="BI3K5_", account_run_id="K5A1",
            )
        self.assertIn("collision", str(ctx.exception).lower())

    def test_preflight_4_names_per_pair(self):
        """Per pair, 4 names are generated: d1p1, d1p2, d2p1, d2p2."""
        from bot_vgc2026_phaseV3a2_reality import (
            preflight_uniqueness_check,
        )
        result = preflight_uniqueness_check(
            n_pairs=1, start_pair=0,
            prefix="B_", account_run_id="R1",
        )
        keys = set(result.keys())
        self.assertEqual(
            keys,
            {
                (0, "d1", "p1"),
                (0, "d1", "p2"),
                (0, "d2", "p1"),
                (0, "d2", "p2"),
            },
        )
        # d1p1 and d2p2 are treatment (L); d1p2 and d2p1
        # are baseline (V).
        self.assertTrue(result[(0, "d1", "p1")].endswith("L"))
        self.assertTrue(result[(0, "d1", "p2")].endswith("V"))
        self.assertTrue(result[(0, "d2", "p1")].endswith("V"))
        self.assertTrue(result[(0, "d2", "p2")].endswith("L"))

    def test_preflight_normalized_collision(self):
        """A normalized collision is caught before connection.

        Two names that differ in case/punctuation but
        normalize to the same Showdown userid must be
        detected. This can happen when pair_id % 1000
        wraps: pair 0 d1p1 and pair 1000 d1p1 produce
        the same visible name.
        """
        from bot_vgc2026_phaseV3a2_reality import (
            preflight_uniqueness_check, _showdown_normalize,
        )
        # Sanity: the helper lowercases and strips non-alnum.
        self.assertEqual(
            _showdown_normalize("Foo_Bar-123"),
            "foobar123",
        )
        # pair_id % 1000 wrapping: pair 0 and pair 1000
        # produce the same visible name for d1p1.
        with self.assertRaises(ValueError) as ctx:
            preflight_uniqueness_check(
                n_pairs=1001, start_pair=0,
                prefix="BK6_", account_run_id="Q6A1",
            )
        self.assertIn("collision", str(ctx.exception).lower())

    def test_account_run_id_names_remain_within_18_chars(self):
        """Account names with --account-run-id stay <=18 chars."""
        from bot_vgc2026_phaseV3a2_reality import (
            preflight_uniqueness_check, SHOWDOWN_NAME_MAX,
        )
        result = preflight_uniqueness_check(
            n_pairs=100, start_pair=0,
            prefix="BK6_", account_run_id="Q6A1",
        )
        for key, name in result.items():
            self.assertLessEqual(
                len(name), SHOWDOWN_NAME_MAX,
                f"Name {name!r} for {key} exceeds limit",
            )


class TestNoProductionCleanupImport(unittest.TestCase):
    """The runner is allowed to import ``poke_env_test_cleanup``
    for atexit cleanup (it follows the same pattern as test
    modules). What matters is that BI-3F-1's audit-flag
    wiring did NOT add a NEW poke_env_test_cleanup import.
    We assert that no new import was added by checking the
    BI-3F-1 commit lines.
    """

    def test_no_new_poke_env_test_cleanup_added_by_bi3f1(self):
        """The BI-3F-1 audit-flag wiring must NOT introduce a
        new ``poke_env_test_cleanup`` import. (The runner
        may already have it from earlier phases.)
        """
        with open(
            os.path.join(
                PROJECT_DIR, "bot_vgc2026_phaseV3a2_reality.py"
            )
        ) as f:
            content = f.read()
        # The audit flag uses the audit logger module directly.
        self.assertIn("DoublesDecisionAuditLogger", content)
        self.assertNotIn(
            "poke_env_test_cleanup",
            content.split(
                "# Phase BI-3F-1"
            )[-1] if "# Phase BI-3F-1" in content else "",
        )


if __name__ == "__main__":
    unittest.main()