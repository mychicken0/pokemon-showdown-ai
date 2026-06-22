# Scripts Organization Plan

**Date**: 2026-06-22
**Status**: Phase 1+2+3 complete. Phase 4 (src/) deferred.

## Final state

```
src/                          # Production bot code (DEFERRED)
  README.md
tests/                        # 101 test files
  __init__.py                 # Makes tests/ importable as package
  test_anti_tr_target_debug.py
  test_bot_doubles_basic_aware.py
  test_bot_doubles_damage_aware.py
  test_status_move_ability_safety.py
  test_target_aware_anti_tr.py
  test_v2k4_regression.py
  test_v2k5_regression.py
  ... (101 total)
scripts/                      # Helper scripts (organized)
  README.md                   # Top-level scripts index
  start_local_showdown.sh
  v2l1_smoke.py
  run_mixed_stability_test.py
  build_planner_dataset.py
  generate_intent_dashboard.py
  run_intent_policy_dryrun.py
  audit_doubles_narrow_ally_heal_paired_638d1.py
  batch_fetch.py
  enrich_source_urls.py
  fetcher.py
  analyze/                    # 15 files (no cross-imports)
  inspect/                    # empty
  eval/                       # empty
  dryrun/                     # empty
  check/                      # 2 files
  diagnose/                   # empty
  fix/                        # 5 files
  build/                      # 4 files
  export/                     # 2 files

archive/                      # Old bot_*.py experiments (60 files)
  bot_battle_selfplay.py
  bot_damage_vs_rule.py
  ... (60 total, all old bot experiments)

run_tests.py                  # Test runner
```

## Migration progress

### Phase 1: Archive safe bot files (DONE)
- 60 `bot_*.py` files moved to `archive/`
- No cross-imports broken

### Phase 2: Move safe scripts to sub-folders (DONE)
- 38 `*.py` files moved to `scripts/<sub>/`
- 8 broken test files reverted to root
- 7 cross-imported script modules reverted to root

### Phase 3: Move tests to tests/ (DONE)
- 101 test files moved to `tests/`
- `tests/__init__.py` created
- 8 test files with cross-imports kept at root
- `run_tests.py` created (handles tests/ subfolder structure)

### Phase 4: Move src/ production code (DEFERRED)
- Production code (bot_doubles_damage_aware.py, etc.) NOT moved
- 124 files import bot_doubles_damage_aware
- 62 files import doubles_decision_audit_logger
- 44 files import bot_doubles_basic_aware
- 15 files import doubles_mechanics
- 10 files import bot_doubles_intent_classifier
- Total: 250+ imports across ~200 files
- Would require:
  - `src/__init__.py` (package)
  - Updating 200+ imports
  - OR adding `sys.path.insert(0, 'src')` to every test
- **Why deferred**: 191 files already moved (61% reduction). The remaining
  122 are mostly production code with cross-imports. Risk: HIGH,
  Benefit: LOW. User can request this explicitly if needed.

## What remains at root

- 122 .py files (down from 313, 61% reduction)
- 23 bot_*.py files (referenced by other files)
- ~50 script files (cross-imports with other scripts)
- 8 test files (cross-imports with scripts)
- ~30 misc Python files (ability_rules, doubles_mechanics, etc.)

## Cross-imports that blocked full migration

- **bot_doubles_damage_aware.py** (124 files) - production bot
- **bot_doubles_basic_aware.py** (44 files) - basic bot
- **doubles_decision_audit_logger.py** (62 files) - audit logger
- **doubles_mechanics.py** (15 files) - mechanics helpers
- **bot_doubles_intent_classifier.py** (10 files) - intent classifier
- **Various script modules** (analyze_*, eval_*, dryrun_*, etc.)

## Test runner

`run_tests.py` handles the tests/ subfolder structure:
- `python run_tests.py test_X` → looks for tests/test_X.py OR test_X.py
- `python run_tests.py -k Magic` → discover with -k filter
- `python run_tests.py --list` → list all test modules
- `python run_tests.py` → run all tests in tests/

## Summary

- 191 files moved (61% reduction at root)
- 177+ tests pass
- 0 code changes (file moves only)
- 0 default flip
- All opt-in policies remain OFF
- Migration is COMPLETE for safe-to-move files
- src/ migration deferred (user request only)
