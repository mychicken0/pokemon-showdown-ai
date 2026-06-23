# ROOT_INDEX.md

**Generated**: 2026-06-22
**Scope**: All `.py` files remaining at the project root (81 files).
**Purpose**: Human navigation layer after Phase ORG-MOVE-2 declutter.

Related docs:
- `SCRIPTS_ORGANIZATION.md` — Migration history and rationale.
- `scripts/README.md` — What's in `scripts/<sub>/`.
- `archive/README.md` — What's in `archive/`.

---

## Why these files are at root

After the migration of safe-to-move files (60 bot experiments → `archive/`,
38 helper scripts → `scripts/<sub>/`, 101 tests → `tests/`, then Phase
ORG-MOVE-2 moved docs/json out, inspect scripts to `scripts/inspect/`,
analyze scripts to `scripts/analyze/`, plus 8 root tests to `tests/`),
**81 `.py` files** remain at root. Categories:

- **23 wrappers** (18 analyze_*.py + 5 inspect_*.py) — root compatibility
  shims that re-export moved modules via `sys.modules` swap.
- **58 production code** — `bot_*.py`, `vgc2026_*.py`, `doubles_*.py`,
  `ability_rules.py`, etc. The user spec for Phase ORG-MOVE-2 said
  NOT to move these (would require full src/ package migration).

The wrappers are an intentional, documented pattern: they are 1-stanza
`sys.modules` swaps that let existing imports continue to work without
modifying any caller. Each wrapper is <15 lines.

---

## Categories (81 files total)

| Count | Category | Why at root |
|------:|----------|-------------|
| 23 | [wrappers (analyze + inspect)](#1-wrappers-23-files) | `sys.modules` re-export shims; safe, no behavior change |
| 23 | [core bot/runtime](#2-core-botruntime-23-files) | Production bots; 124+ files import `bot_doubles_damage_aware` |
| 5 | [core modules](#3-core-modules-5-files) | `doubles_*` and `ability_rules`; 100+ importers total |
| 12 | [VGC helpers](#4-vgc-helpers-12-files) | V3a/V3b/V3c training + matchup evaluators; cross-imports |
| 16 | [production misc](#5-production-misc-16-files) | Standalone scripts with no obvious sub-folder home |
| 2 | [infrastructure](#6-infrastructure-2-files) | `run_tests.py`, `conftest.py` — must be at root |

---

## 1. wrappers (23 files)

Tiny `sys.modules` re-export shims. The actual implementations moved to
`scripts/analyze/` or `scripts/inspect/`. The wrapper does:

```python
import sys
import scripts.analyze.X as _impl
sys.modules[__name__] = _impl
```

This makes `import X` and `from X import Y` resolve to the moved module
without any caller modification.

### File list — analyze wrappers (18)

```
analyze_anti_setup_dryrun.py
analyze_control_move_evidence.py
analyze_doubles_narrow_ally_heal_paired_repair.py
analyze_doubles_support_move_target_safety_paired.py
analyze_doubles_turn_level.py
analyze_doubles_voluntary_switch_paired.py
analyze_turn_level_offline_dataset_quality.py
analyze_vgc2026_phaseV2c1.py
analyze_vgc2026_phaseV2d_qualification.py
analyze_vgc2026_phaseV2e_failures.py
analyze_vgc2026_phaseV2f_qualification.py
analyze_vgc2026_phaseV2g_failures.py
analyze_vgc2026_phaseV2h_feature_stability.py
analyze_vgc2026_phaseV2i_matchup_evaluator.py
analyze_vgc2026_phaseV2j_lead_matchups.py
analyze_vgc2026_phaseV2k_lead_matchups.py
analyze_vgc2026_phaseV3a2_reality.py
analyze_vgc2026_team_preview_dataset_quality.py
```

### File list — inspect wrappers (5)

```
inspect_vgc2026_phaseV2g_pair.py
inspect_vgc2026_phaseV2h_feature.py
inspect_vgc2026_phaseV2i_matchup.py
inspect_vgc2026_phaseV2j_lead_matchup.py
inspect_vgc2026_phaseV2k_lead_matchup.py
```

### Why at root

These 23 wrappers exist so that:

- Test files in `tests/` can do `from analyze_X import Y` and find the
  wrapper, which delegates to `scripts/analyze/X.py`.
- Test subprocess invocations like `python -c "import inspect_X"`
  resolve the wrapper at root, which delegates to `scripts/inspect/X.py`.
- Tests that subprocess-run `python inspect_X.py` with `cwd=tests/` still
  fail for 5 inspect scripts (pre-existing bug, see Section 4 below).

### Safe future migration condition

Remove wrappers when:

1. All callers are updated to use `from scripts.analyze.X import Y` or
   `from scripts.inspect.X import Y` style.
2. Test subprocess invocations are updated to use the new path.
3. The chain V2d→V2e, V2f→V2g→V2h, V2j→V2k has been split into proper
   Python packages with relative imports.

Until then, the wrappers are a cheap, low-risk compatibility layer.

---

## 2. core bot/runtime (23 files)

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

Per Phase ORG-MOVE-2 spec, **do not move in this phase**. Move only
when:

1. `src/` becomes a real package with `__init__.py`.
2. All 124+ importers are updated to `from src.bot_doubles_damage_aware import ...`.
3. The `DoublesDamageAwareConfig` discovery pattern (read by analyzer
   tools) is verified to still work after the move.
4. `poke_env_test_cleanup` import ordering is preserved.

---

## 3. core modules (5 files)

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

### Safe future migration condition

Move only when moving all 80+ importers in the same change. Suggested
location: `src/core/` with a thin re-export shim at root for backward
compatibility during the transition.

---

## 4. VGC helpers (12 files)

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
  `analyze_vgc2026_phaseV2i_matchup_evaluator` (now in `scripts/analyze/`,
  reachable via wrapper) and tests in `tests/`.
- `vgc_team_pool` imported by `analyze_vgc2026_preview_policy_failures`
  (in `scripts/analyze/`) and one test.
- The V3a/V3b/V3c training scripts cross-reference each other via
  the V3c dataset format.

### Safe future migration condition

Move to `scripts/eval/` (the V2e/V2i/V2j family) or
`scripts/eval/vgc2026/` (the V3 family) once the `scripts/` sys.path
hack is exposed to subprocess invocations.

### Pre-existing breakage (not a regression)

Five test files (`test_vgc2026_phaseV2{h,i,j,k}` and others) use
`subprocess.run([python, "inspect_X.py"], cwd=tests/)`. These expect
the inspect script at `tests/inspect_X.py`, but in HEAD the inspect
scripts were at root, so these tests were already failing before
this migration. After this migration, the inspect scripts are at
`scripts/inspect/`, and the tests still fail (with a different error
message). This is **pre-existing breakage** — not a regression.

---

## 5. production misc (16 files)

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
  (kept at root per Section 4).
- `scenario_probe.py` and `team_preview_policy.py` are referenced by
  tests in `tests/` and the VGC helpers in Section 4.
- `rk9_playwright_scraper.py` uses browser automation (per AGENTS.md
  this is restricted, but this file is not in the battle pipeline —
  it is kept for one-off RK9 URL recovery only).

### Safe future migration condition

Most of these can move to `scripts/eval/` or `scripts/build/` once
the corresponding cross-imports are resolved. `poke_env_test_cleanup`
should move to `tests/_support/` and be made a `conftest.py`-style
auto-import helper.

---

## 6. infrastructure (2 files)

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

## Quick lookup: which test imports which root module

| Test | Imports (at root) | Why at root |
|---|---|---|
| `tests/test_diagnose_protect_usage` | `diagnose_protect_usage` | both kept at root |
| `tests/test_build_turn_level_offline_dataset` | `build_turn_level_offline_dataset` | both kept at root |
| `tests/test_dryrun_turn_level_offline_policy` | `dryrun_turn_level_offline_policy` | both kept at root |
| `tests/test_v2k4_regression` | `analyze_vgc2026_phaseV2k_lead_matchups` (via wrapper) | chain V2j→V2k |
| `tests/test_v2k5_regression` | `analyze_vgc2026_phaseV2k_lead_matchups` (via wrapper) | chain V2j→V2k |
| `tests/test_vgc2026_phaseV2g` | `analyze_vgc2026_phaseV2g_failures` (via wrapper, subprocess) | chain V2f→V2g |
| `tests/test_vgc2026_phaseV2e` | `analyze_vgc2026_phaseV2e_failures` (via wrapper) | chain V2d→V2e |
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
- `docs/phases/` — implementation plans for historical phases
  (moved from root in Phase ORG-MOVE-2).
- `docs/commit_boundaries/` — commit-boundary audit artifacts.
- `docs/phase7_proposal.md` — Phase 7 RL training proposal
  (RL-DATA-5). Status: `READY_FOR_PHASE7_PROPOSAL_BUT_NOT_APPROVED`.
  Training NOT approved. Requires explicit user authorization
  and AGENTS.md sign-off.
- `docs/wt_weather_terrain_opt_in.md` — Weather/Terrain
  positive scoring opt-in implementation (WT-3 through
  WT-4g, closed). Status:
  `WT4G_OPT_IN_READY_DEFAULT_OFF`. Opt-in implemented,
  default OFF, not default-adopted, no 100-pair benchmark
  required before moving on.
- `data/vgc2026_teams_detailed.json` — VGC 2026 team detail dataset
  (moved from root in Phase ORG-MOVE-2).
