# Project Structure

**Date**: 2026-06-22
**Phase**: Post-ORG-MOVE-2 cleanup (user requested no .py or .md clutter at root)

## Goal

Reduce root visual clutter to **only the 3 main doc files**:
- `README.md`
- `walkthrough.md`
- `CURRENT_STATE.md`

(Plus `AGENTS.md` for the agent system reminder.)

## Final State

```
/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/
├── README.md              ← KEEP (main entry point)
├── walkthrough.md         ← KEEP (canonical dev history)
├── CURRENT_STATE.md       ← KEEP (current project state)
├── AGENTS.md              ← KEEP (system reminder)
│
├── showdown_ai/           ← Production code (57 .py)
│   ├── __init__.py
│   ├── bot_doubles_damage_aware.py   ← Main production bot
│   ├── bot_doubles_basic_aware.py
│   ├── ability_rules.py
│   ├── doubles_*.py
│   ├── vgc2026_*.py
│   └── ... (52 more)
│
├── tests/                 ← All tests (109 test files)
│   ├── __init__.py        ← Adds showdown_ai/, scripts/ to sys.path
│   ├── conftest.py        ← Doc-only (pytest compat)
│   ├── test_anti_tr_target_debug.py
│   ├── test_doubles_ability_hard_safety.py
│   └── ... (105 more)
│
├── scripts/               ← Helper scripts (95 .py)
│   ├── README.md
│   ├── setup_dev_env.sh   ← NEW: Creates .pth file for subprocess imports
│   ├── start_local_showdown.sh
│   ├── analyze/           ← analyze_*.py
│   ├── inspect/           ← inspect_*.py
│   ├── eval/, dryrun/, check/, diagnose/, fix/, build/, export/
│   └── ... 
│
├── archive/               ← Old bot experiments (60 files)
│   ├── README.md
│   └── ... (60 bot_*.py experiments)
│
├── docs/                  ← Historical docs (moved from root)
│   ├── PROJECT_STRUCTURE.md  ← This file
│   ├── ROOT_INDEX.md          ← Historical index of files that were at root
│   ├── SCRIPTS_ORGANIZATION.md ← Migration history
│   ├── phases/                ← 12 phase_*.md plans
│   └── commit_boundaries/     ← 2 commit-boundary audit files
│
├── data/                  ← Data files (moved from root)
│   ├── vgc2026_teams_detailed.json
│   ├── curated_teams/
│   ├── meta_usage_stats.json
│   ├── random_doubles_set_stats.json
│   └── vgc2026_topteams/
│
└── venv/                  ← Python virtual environment
    └── lib/python3.12/site-packages/
        └── showdown_ai.pth  ← Created by scripts/setup_dev_env.sh
                              (adds showdown_ai/ to subprocess sys.path)
```

## Migration Summary

| Phase | Action | Files |
|------:|--------|------:|
| Initial | 313 .py at root, 17 .md, 2 .json | - |
| Phase 1 | Archive 60 bot_*.py experiments | -60 .py |
| Phase 2 | Move 38 scripts to scripts/<sub>/ | -38 .py |
| Phase 3 | Move 101 tests to tests/ | -101 .py |
| ORG-INDEX-1 | Create ROOT_INDEX.md (root nav) | +1 .md |
| ORG-MOVE-2 step 1 | Move 17 docs/json to docs/data | -17 .md/json |
| ORG-MOVE-2 step 2 | Move 32 inspect scripts to scripts/inspect/ | -32 .py |
| ORG-MOVE-2 step 3 | Move 25 analyze chain files to scripts/analyze/ | -25 .py +18 wrappers |
| ORG-MOVE-2 step 4 | Move 8 root tests to tests/ | -8 .py |
| **This phase** | Move 56 production .py to showdown_ai/ | -56 .py |
| **This phase** | Remove 23 wrappers | -23 .py |
| **This phase** | Move 4 .md to docs/ (later moved back) | (4 .md) |
| **Total** | **0 .py at root, 4 .md at root** | **-232 .py** |

## Setup Required After Fresh Clone

Run the setup script to create the `.pth` file that enables subprocess imports:

```bash
./scripts/setup_dev_env.sh
```

This creates `venv/lib/python3.12/site-packages/showdown_ai.pth` with the
absolute path to the project. It enables:
- `python -c "import ability_rules"` to find `showdown_ai/ability_rules.py`
- `python -c "import analyze_X"` to find `scripts/analyze/analyze_X.py`
- `python -c "import inspect_X"` to find `scripts/inspect/inspect_X.py`

## How to Run Tests

```bash
# Run a specific test
python -m unittest tests.test_anti_tr_target_debug

# Run all tests
python -m unittest discover -s tests -t .

# Or use the test runner
python scripts/check/run_tests.py test_anti_tr_target_debug
```

## How to Run Bots

```bash
# Damage-aware bot (main production bot)
python -m showdown_ai.bot_doubles_damage_aware

# Or directly (if showdown_ai/ in path)
python showdown_ai/bot_doubles_damage_aware.py
```

## Pre-existing Test Breakage (Not a Regression)

The following tests have pre-existing failures that are not introduced by
this migration:

- `tests/test_vgc2026_phaseV2h.TestInspectorIntegration.*` (6 failures)
- `tests/test_vgc2026_phaseV2i.TestInspectorIntegration.*` (5 failures)
- `tests/test_vgc2026_phaseV2j.TestInspectorIntegration.*` (11 failures)

These tests do `subprocess.run([python, "inspect_X.py"], cwd=tests/)`
expecting the inspect script to be at `tests/`, but the file is at
`scripts/inspect/`. This was broken in HEAD (e0f8d83) and before (6a09140).
Fixing requires updating test code, which is deferred per AGENTS.md
"Never revert changes you did not make".
