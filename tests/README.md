# tests/

**Unit tests** - All unittest-based test files.

## What goes here

All `test_*.py` files (109 currently at project root):

- `test_doubles_ability_hard_safety.py`
- `test_target_aware_anti_tr.py`
- `test_anti_tr_target_debug.py`
- `test_status_move_ability_safety.py`
- `test_planner_intent_detector.py`
- `test_scenario_probe.py`
- ... (and 100+ more)

## Why organize?

Currently 109 test files live at the project root mixed with bot
source, scripts, and analyzers. This makes:

- Imports confusing (you have to scroll past 100 test files to find production code)
- Test discovery slower (no isolation)
- Risk of accidental edits to bot code while looking at tests

## Migration plan (NOT YET MOVED)

Currently the test files are still at the project root.
This folder is reserved for the future move. The user opted for
"create folders + placeholders only" - safe approach.

## When ready to migrate

```bash
# Example (run manually when ready):
git mv test_doubles_ability_hard_safety.py tests/
git mv test_target_aware_anti_tr.py tests/
# ... etc
```

After moving, update:
- `conftest.py` if you use pytest fixtures
- `Makefile` or test runner config (if any)
- Any CI/CD config that references test paths
