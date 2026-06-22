# ROOT_INDEX.md

**Generated**: 2026-06-22
**Scope**: All `.py` files remaining at the project root (123 files).
**Purpose**: Human navigation layer. No file moves, no src/ migration,
no import rewrites. This is documentation only.

Related docs:
- `SCRIPTS_ORGANIZATION.md` — Migration history and rationale.
- `scripts/README.md` — What's in `scripts/<sub>/`.
- `archive/README.md` — What's in `archive/`.

---

## Why these files are at root

After the migration of safe-to-move files (60 bot experiments → `archive/`,
38 helper scripts → `scripts/<sub>/`, 101 tests → `tests/`), 123 `.py`
files remain at root. Every one of them has cross-imports with other
root files. Moving them would require:

- `src/` becoming a real Python package (`src/__init__.py`).
- Updating 200+ import lines across the test suite and the moved files
  themselves.
- Updating subprocess `python -c "import X"` calls inside test files
  (e.g. `test_vgc2026_phaseV2g.py::test_natural_termination`).

This Phase **ORG-INDEX-1** chose a human-navigation layer instead, with
clear categories, file lists, and "safe future migration condition" notes.

---

## Categories (123 files total)

| Count | Category | Why at root |
|------:|----------|-------------|
| 23 | [core bot/runtime](#1-core-botruntime-23-files) | Production bots; 124+ files import `bot_doubles_damage_aware` |
| 5 | [core modules](#2-core-modules-5-files) | `doubles_*` and `ability_rules`; 100+ importers total |
| 25 | [analyzers left at root](#3-analyzers-left-at-root-25-files) | Cross-imports with each other (chain: V2d→V2e, V2f→V2g→V2h, V2j→V2k) |
| 32 | [inspectors left at root](#4-inspectors-left-at-root-32-files) | Each imports core bot or another inspector |
| 12 | [VGC helpers](#5-vgc-helpers-12-files) | V3a/V3b/V3c training + matchup evaluators; cross-imports |
| 8 | [tests left at root](#6-tests-left-at-root-8-files) | Test files that `subprocess.run` an import; can't be in `tests/` |
| 2 | [infrastructure](#7-infrastructure-2-files) | `run_tests.py`, `conftest.py` — must be at root |
| 16 | [production misc](#8-production-misc-16-files) | Standalone scripts with no obvious sub-folder home |

---

## 1. core bot/runtime (23 files)

The actual bot implementations and benchmark drivers. The headline file
is `bot_doubles_damage_aware.py` (the main production bot per AGENTS.md).

### File list

```
bot_damage_aware.py
bot_doubles_absorb_error_audit.py
bot_doubles_anti_setup_eligibility.py
bot_doubles_basic_aware.py
bot_doubles_damage_aware.py          ← main production bot
bot_doubles_decision_graph_viewer.py ← PySide6 dashboard (Qt UI)
bot_doubles_dynamic_move_type_safety_benchmark.py
bot_doubles_dynamic_move_type_targeted_qualification.py
bot_doubles_intent_classifier.py
bot_doubles_safe_random.py
bot_doubles_singleton_ability_safety_benchmark.py
bot_doubles_support_move_target_safety_paired_qualification.py
bot_doubles_voluntary_switch_diagnostics.py
bot_doubles_voluntary_switch_paired_qualification.py
bot_doubles_voluntary_switch_surface_probe.py
bot_rule_based.py
bot_switch_aware.py
bot_vgc2026_phaseV2c.py
bot_vgc2026_phaseV2d_qualification.py
bot_vgc2026_phaseV2d_smoke.py
bot_vgc2026_phaseV2f_qualification.py
bot_vgc2026_phaseV3a2_reality.py
bot_vgc2026_scripted_opp.py
```

### Why at root

- `bot_doubles_damage_aware.py` is imported by **124** other files
  (tests, scripts, archive, scripts/analyze, scripts/eval).
- The 23 files are referenced by 250+ cross-imports combined.
- `bot_doubles_decision_graph_viewer.py` requires `PySide6` (Qt UI
  dashboard) and is invoked as a standalone tool, not imported.

### Safe future migration condition

Move only when:

1. `src/` becomes a real package with `__init__.py`.
2. All 124+ importers are updated to `from src.bot_doubles_damage_aware import ...`.
3. The `DoublesDamageAwareConfig` discovery pattern (read by analyzer
   tools) is verified to still work after the move.
4. `poke_env_test_cleanup` import ordering is preserved.

---

## 2. core modules (5 files)

Pure helpers used everywhere.

### File list

```
ability_rules.py                  ← status-move vs ability safety (Mold Breaker, Aroma Veil, etc.)
doubles_battle_logger.py          ← battle event logger
doubles_decision_audit_logger.py  ← main audit logger (read by every analyzer)
doubles_decision_graph_model.py   ← data model for decision graph viewer
doubles_mechanics.py              ← type chart, ability, item, status helpers
```

### Why at root

- `doubles_decision_audit_logger.py` imported by 62 files.
- `doubles_mechanics.py` imported by 15 files.
- `ability_rules.py` imported by 3 files, but referenced by every
  anti-status/anti-ability policy (CONTROL-PRIORITY-2A).
- These are stable, low-churn files. They were kept at root because
  moving them would require updating 80+ importers, most of which are
  tests that we just moved to `tests/`.

### Safe future migration condition

Move only when moving all 80+ importers in the same change. Suggested
location: `src/core/` with a thin re-export shim at root for backward
compatibility during the transition.

---

## 3. analyzers left at root (25 files)

One-off analysis scripts. Most are historical (Phase V2/V3 eval results).

### File list

**Chain imports (must move together):**

```
analyze_vgc2026_phaseV2d_qualification.py   ← base
analyze_vgc2026_phaseV2e_failures.py        ← imports V2d
analyze_vgc2026_phaseV2f_qualification.py   ← base
analyze_vgc2026_phaseV2g_failures.py        ← imports V2f
analyze_vgc2026_phaseV2h_feature_stability.py ← imports V2g
analyze_vgc2026_phaseV2j_lead_matchups.py   ← base
analyze_vgc2026_phaseV2k_lead_matchups.py   ← imports V2j
```

**Standalone (could move to `scripts/analyze/` if scripts/ were on sys.path):**

```
analyze_anti_setup_dryrun.py
analyze_control_move_evidence.py
analyze_doubles_decision_audit.py
analyze_doubles_narrow_ally_heal_paired.py
analyze_doubles_narrow_ally_heal_paired_repair.py
analyze_doubles_support_move_target_safety_paired.py
analyze_doubles_switch_per_turn.py
analyze_doubles_turn_level.py
analyze_doubles_voluntary_switch_paired.py
analyze_doubles_voluntary_switch_surface_probe.py
analyze_setup4_bonus_sweep.py
analyze_setup_move_evidence.py
analyze_turn_level_offline_dataset_quality.py
analyze_vgc2026_phaseV2c.py
analyze_vgc2026_phaseV2c1.py
analyze_vgc2026_phaseV3a2_reality.py
analyze_vgc2026_team_preview_dataset_quality.py
```

### Why at root

- The chain files (V2d/V2e, V2f/V2g/V2h, V2j/V2k) import each other
  with `import analyze_X` — Python can only resolve this if all are in
  the same directory on `sys.path`.
- The 18 standalone ones have test files that do
  `subprocess.run([sys.executable, "-c", "import analyze_X"])`. The
  subprocess does NOT have the `tests/__init__.py` sys.path hack.
- Earlier attempt to move 21 of these to `scripts/analyze/` was
  reverted because 1 V2g test (`test_natural_termination`) failed.

### Safe future migration condition

Move only when:

1. All chain files are moved together to `scripts/analyze/`.
2. Tests `test_vgc2026_phaseV2g` etc. update their subprocess
   `python -c` invocations to use `sys.path.insert(0, 'scripts/analyze')`
   or use a shim entry point.
3. `tests/__init__.py`'s sys.path hack is also exposed at the
   subprocess level (e.g. via `PYTHONPATH` env var).

---

## 4. inspectors left at root (32 files)

Case inspection scripts for debugging specific battles. Each loads
audit logs and prints a case view.

### File list (sample, 32 total)

```
inspect_ability_hard_safety_cases.py
inspect_absorb_error_cases.py
inspect_decision_timing_cases.py
inspect_disabled_safety_feature_cases.py
inspect_doubles_audit_battle.py
inspect_dynamic_move_type_cases.py
inspect_forced_switch_replacement_cases.py
inspect_forced_switch_replacement_tuning.py
inspect_known_absorb_cases.py
inspect_known_ally_redirection_cases.py
inspect_lost_battle.py
inspect_partial_spread_cases.py
inspect_priority_field_block_cases.py
inspect_revealed_move_switch_cases.py
inspect_runtime_singleton_ability_state.py
inspect_singleton_ability_local_dex.py
inspect_speed_priority_cases.py
inspect_stale_target_cases.py
inspect_stat_drop_pressure_quality.py
inspect_stat_drop_switch_cases.py
inspect_stat_drop_switch_scoring_cases.py
inspect_support_move_target_cases.py
inspect_switch_candidate_safety_cases.py
inspect_vgc2026_phaseV2e_pair.py
inspect_vgc2026_phaseV2g_pair.py
inspect_vgc2026_phaseV2h_feature.py
inspect_vgc2026_phaseV2i_matchup.py
inspect_vgc2026_phaseV2j_lead_matchup.py
inspect_vgc2026_phaseV2k_lead_matchup.py
inspect_vgc2026_preview_pair.py
inspect_vgc2026_runtime_parity.py
inspect_voluntary_switch_quality_cases.py
```

### Why at root

- Every inspector imports `bot_doubles_damage_aware` or
  `doubles_decision_audit_logger` or `doubles_mechanics`.
- Many also import each other or share helper modules
  (e.g. `inspect_vgc2026_phaseV2k_lead_matchup.py` imports from
  `vgc2026_lead_matchup_evaluator_v3`).
- They are kept at root so they can be invoked as
  `python inspect_X.py` from the project root.

### Safe future migration condition

Move only when moving all 32 together to `scripts/inspect/`, with a
conftest.py or PYTHONPATH env var exposing the project root and
`scripts/`. Suggested entry points: `python -m scripts.inspect.inspect_X`.

---

## 5. VGC helpers (12 files)

Phase V3 (VGC 2026 preview learning) training/eval/feature scripts.

### File list

```
vgc2026_common_plan_evaluator.py        ← common base for V2i/V2j/V2k
vgc2026_lead_matchup_evaluator_v3.py
vgc2026_matchup_evaluator_v2.py
vgc2026_phaseV3a_learn_preview.py       ← V3a offline learning baseline
vgc2026_phaseV3b1_audit.py              ← V3b val_acc diagnostic
vgc2026_phaseV3b_opponent_features.py   ← V3b features
vgc2026_phaseV3b_train.py               ← V3b training
vgc2026_phaseV3c1_train.py              ← V3c.1 training
vgc2026_phaseV3c2_reality.py            ← V3c.2 20-pair reality check
vgc2026_phaseV3c_dataset.py             ← V3c dataset builder
vgc2026_plan_features.py
vgc_team_pool.py
```

### Why at root

- `vgc2026_common_plan_evaluator` imported by 6 files including
  `analyze_vgc2026_phaseV2i_matchup_evaluator` (in `scripts/analyze/`
  after the partial move) and tests in `tests/`.
- `vgc_team_pool` imported by `analyze_vgc2026_preview_policy_failures`
  (in `scripts/analyze/`) and one test.
- The V3a/V3b/V3c training scripts cross-reference each other via
  the V3c dataset format.

### Safe future migration condition

Move to `scripts/eval/` (the V2e/V2i/V2j family) or
`scripts/eval/vgc2026/` (the V3 family) once the `scripts/` sys.path
hack is exposed to subprocess invocations. The V3 family is naturally
a sub-folder because it has its own dataset format.

---

## 6. tests left at root (8 files)

These test files are kept at root instead of `tests/` because they
spawn subprocesses that `import` a script module by name, and the
subprocess does not inherit the `tests/__init__.py` sys.path hack.

### File list

```
test_analyze_vgc2026_team_preview_dataset_quality.py
  Phase RL-2 — Tests for the read-only team-preview dataset quality analyzer.
test_build_turn_level_offline_dataset.py
  Phase RL-5 — Tests for the turn-level offline dataset builder.
test_diagnose_protect_usage.py
  Phase PROTECT-1 — Tests for the Protect usage diagnostic.
test_dryrun_turn_level_offline_policy.py
  Phase RL-7 — Tests for the offline policy dry-run feasibility script.
test_vgc2026_phaseV2e.py
  Test suite for VGC 2026 Phase V2e.1.
test_vgc2026_phaseV3a_learn_preview.py
  Phase V3a — VGC Preview Learning Baseline Tests.
test_vgc2026_phaseV3c2a_analyzer_fix.py
  Tests for Phase V3c.2a analyzer perspective fix.
test_vgc2026_preview_policy_diagnostics.py
  Test suite for VGC 2026 Preview Policy Diagnostics — Phase V2d.
```

### Why at root

- All 8 either `import diagnose_protect_usage` (kept at root because
  scripts/diagnose/ has its own cross-imports) or `import` a chain
  analyzer that's still at root.
- They live next to the module they test (Python auto-adds the test
  file's directory to `sys.path`).
- Moving them to `tests/` would require either:
  - Moving the corresponding module to `src/`, OR
  - Adding a `sys.path` hack to the test file itself.

### Safe future migration condition

Move when the corresponding modules move to `src/` or `scripts/`.
The 8 tests can be moved to `tests/` immediately if they each
add `sys.path.insert(0, project_root)` at the top.

---

## 7. infrastructure (2 files)

```
run_tests.py
conftest.py
```

### Why at root

- `run_tests.py` is the test runner script — must be invokable from
  the project root.
- `conftest.py` is the project-wide pytest config / sys.path doc
  placeholder. (Currently a documentation-only file because tests use
  `unittest`, not `pytest`.)

### Safe future migration condition

These stay at root permanently. `run_tests.py` is the entry point
for `python run_tests.py test_X`. `conftest.py` is the project
pytest config entry point.

---

## 8. production misc (16 files)

Standalone scripts that don't fit the other categories.

### File list

```
battle_logger.py                      ← simple battle event logger
build_turn_level_offline_dataset.py   ← Phase RL-5 dataset builder
diagnose_protect_usage.py             ← Phase PROTECT-1 diagnostic
dryrun_turn_level_offline_policy.py   ← Phase RL-7 dry-run
eval_vgc2026_phaseV2e_policies.py     ← V2e.1 offline policy comparison
eval_vgc2026_policies_offline.py      ← offline VGC policy comparison
meta_model.py                         ← Phase 5 opponent modeling
parse_meta_stats.py                   ← Smogon statistics parser
poke_env_test_cleanup.py              ← MUST be at root (test-only import shim)
random_set_model.py                   ← Phase 5.1 random-set modeling
rebuild_canonical.py                  ← canonical dataset rebuild
rk9_playwright_scraper.py             ← browser-automation fallback (NOT used in bot)
scenario_probe.py                     ← Phase SCENARIO-2 loader/validator
team_preview_policy.py                ← VGC team preview policies
validate_vgc2026_teams.py             ← Phase T6 validator
validate_vgc2026_teams_v2.py          ← V2 validator
```

### Why at root

- `poke_env_test_cleanup` is a test-only import shim that must run
  before any `poke_env` import. It is referenced by tests (so it
  must be importable from `tests/`).
- The V2e policy eval scripts cross-import `vgc2026_common_plan_evaluator`
  (kept at root per Section 5).
- `scenario_probe.py` and `team_preview_policy.py` are referenced by
  tests in `tests/` and the VGC helpers in Section 5.
- `rk9_playwright_scraper.py` uses browser automation (per AGENTS.md
  this is restricted, but this file is not in the battle pipeline —
  it is kept for one-off RK9 URL recovery only).

### Safe future migration condition

Most of these can move to `scripts/eval/` or `scripts/build/` once
the corresponding cross-imports are resolved. `poke_env_test_cleanup`
should move to `tests/_support/` and be made a `conftest.py`-style
auto-import helper.

---

## Quick lookup: which test imports which root module

| Test (at root or in tests/) | Imports (at root) | Why at root |
|---|---|---|
| `test_diagnose_protect_usage` | `diagnose_protect_usage` | both kept at root |
| `test_build_turn_level_offline_dataset` | `build_turn_level_offline_dataset` | both kept at root |
| `test_dryrun_turn_level_offline_policy` | `dryrun_turn_level_offline_policy` | both kept at root |
| `test_v2k4_regression` | `analyze_vgc2026_phaseV2k_lead_matchups` | chain V2j→V2k |
| `test_v2k5_regression` | `analyze_vgc2026_phaseV2k_lead_matchups` | chain V2j→V2k |
| `test_vgc2026_phaseV2g` | `analyze_vgc2026_phaseV2g_failures` (subprocess) | chain V2f→V2g |
| `test_vgc2026_phaseV2e` | `eval_vgc2026_phaseV2e_policies` | both kept at root |
| `tests/test_*` (most) | `bot_doubles_damage_aware` | 124 importers |

---

## Cross-references

- `SCRIPTS_ORGANIZATION.md` — migration history, current state, what was
  tried, what was reverted.
- `scripts/README.md` — what is in `scripts/analyze/`,
  `scripts/inspect/`, etc. (sub-folder README).
- `archive/README.md` — what is in `archive/` (60 bot experiments).
- `walkthrough.md` — the canonical development history. Search for the
  phase name (e.g. CONTROL-PRIORITY-2A) to find the work log.
