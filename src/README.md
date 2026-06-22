# src/

**Production bot code** - Core bot implementations and shared infrastructure.

## What goes here

Core production modules used by the running bot and its supporting systems:

- **Main bot**: `bot_doubles_damage_aware.py` (the production doubles bot)
- **Basic bot**: `bot_doubles_basic_aware.py` (fallback bot for non-doubles formats)
- **Other bot variants**: `bot_damage_aware.py`, `bot_damage_vs_rule.py`, etc.
- **Helpers / rules**: `ability_rules.py`, `doubles_mechanics.py`
- **Logging**: `battle_logger.py`, `doubles_battle_logger.py`, `doubles_decision_audit_logger.py`
- **Models**: `doubles_decision_graph_model.py`

## Migration plan (NOT YET MOVED)

Currently the candidate files are still at the project root.
This folder is reserved for the future move. The user opted for
"create folders + placeholders only" - safe approach, no actual
file moves yet.

## When ready to migrate

```bash
# Example (run manually when ready):
git mv bot_doubles_damage_aware.py src/
git mv bot_doubles_basic_aware.py src/
git mv ability_rules.py src/
# ... etc
```

After moving, update imports in:
- All test files (test_*.py)
- All scripts (scripts/*.py and any utility scripts at root)
- All audit loggers that reference the bot modules
- Any cross-references in logs/phase*.md reports
