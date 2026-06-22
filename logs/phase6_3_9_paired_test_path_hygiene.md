# Phase 6.3.9 — Paired-Test Path Hygiene

**Date**: 2026-06-22
**Status**: `PATH_HYGIENE_FIXED`
**Phase**: 6.3.9 (hygiene only — no behavior change)

## Issue

`tests/test_doubles_support_move_target_safety_paired.py` had 3 pre-existing
test failures caused by the root → `showdown_ai/` migration:

1. `test_cli_missing_artifact_tag_fails`
2. `test_cli_refuses_overwrite_without_flag`
3. `test_no_resource_warning_in_paired_helpers`

## Root cause

Three combined path issues:

1. **`PROJECT_ROOT` was wrong.** The test computed
   `PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))` which
   pointed to `tests/` (parent of the test file) instead of the actual
   project root (parent of `tests/`).

2. **`QUALIFIER` was the wrong path.** The qualifier script
   `bot_doubles_support_move_target_safety_paired_qualification.py`
   had been moved to `showdown_ai/` but the test's `QUALIFIER`
   constant pointed to the old root-level path.

3. **Subprocess invocations lacked `PYTHONPATH`.** The qualifier imports
   `bot_doubles_damage_aware` which imports `doubles_engine.protocol`.
   The subprocess for the 3 tests did not have `doubles_engine/`
   on its `sys.path`, so the import failed before the qualifier
   could even run.

## Files changed

- `tests/test_doubles_support_move_target_safety_paired.py`
  - Fixed `PROJECT_ROOT` to go up two levels from `__file__`
    (now consistent with the existing `REPO_ROOT` definition).
  - Updated `QUALIFIER` to include the `showdown_ai/` subfolder.
  - Updated `test_no_resource_warning_in_paired_helpers`
    subprocess invocation:
    - Script path: `tests/test_doubles_support_move_target_safety_paired.py`
      (was: bare name, which failed after the move).
    - Added `env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}` so the
      subprocess can find `doubles_engine/`.
  - Updated both `TestCLI` tests to pass the same `PYTHONPATH` env.

## Tests run and results

| Test file | Before | After |
|-----------|-------:|------:|
| `test_doubles_support_move_target_safety_paired.py` | 90 pass, 3 fail | **93 pass** |
| `test_doubles_support_move_target_safety.py` | 91 pass | 91 pass |
| `test_doubles_engine_support_targets.py` | 67 pass | 67 pass |
| **Total** | **248 pass, 3 fail** | **251 pass** |

## Confirmation: hygiene only

- ✅ No commit (per task)
- ✅ No push (per task)
- ✅ No production behavior change
- ✅ No scoring/default changes
- ✅ No WT/Anti-TR changes
- ✅ No test_51 touch
- ✅ No new behavior flags
- ✅ No file moves
- ✅ No symlinks
- ✅ No duplicate root script

## Tests unchanged

The 3 fixed tests now pass and test the same behavior as before:
- `test_cli_missing_artifact_tag_fails` — qualifier still requires
  `--artifact-tag` (verified by stderr containing "artifact-tag")
- `test_cli_refuses_overwrite_without_flag` — qualifier still refuses
  to overwrite (verified by stderr containing "overwrite")
- `test_no_resource_warning_in_paired_helpers` — no ResourceWarning
  is emitted (verified by successful returncode)

## Remaining TODOs (none introduced by this phase)

None. The 3 pre-existing failures are now fixed. The test file path
expectations and the `PYTHONPATH` setup match the actual project
structure after the root → `showdown_ai/` migration.

## Note on REPO_ROOT vs PROJECT_ROOT

After the fix, `REPO_ROOT` and `PROJECT_ROOT` in the test file have
the same value (both point to the actual project root). They were
defined identically by different paths:

```python
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

This is a side effect of the fix. Consolidating them into a single
variable is out of scope for this hygiene phase.
