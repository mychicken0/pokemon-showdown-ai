# archive/

**Archived old bot experiments** - Old bot variants and experiments kept
for historical reference but not used by the main pipeline.

## What goes here

Old `bot_*.py` experiment files (83 files at root):

- `bot_all_target_immune_spread_benchmark.py`
- `bot_battle_selfplay.py`
- `bot_damage_vs_rule.py` and variants
- `bot_doubles_ability_aware_benchmark.py`
- `bot_doubles_ability_hard_safety_benchmark.py`
- `bot_doubles_absorb_error_audit.py`
- `bot_doubles_adopted_ability_safety_verification.py`
- `bot_doubles_anti_setup_eligibility.py`
- ... (80+ more)

## Why archive?

These are one-off experiments from previous phases that are no
longer the production bot. The current production bot is
`bot_doubles_damage_aware.py` (kept in `src/` after migration).

Archiving (instead of deleting) preserves:
- Historical reference for what was tried
- Code that may be revived if a feature is re-explored
- The git history of changes to these files

## Migration plan (NOT YET MOVED)

The user opted for "create folders + placeholders only" - safe
approach. Actual file moves are deferred.

## When ready to migrate

```bash
# Example (run manually when ready):
git mv bot_all_target_immune_spread_benchmark.py archive/
git mv bot_battle_selfplay.py archive/
# ... etc (preserve git history with git mv)
```

⚠️ **Do NOT delete** these files. They are kept for historical
reference. If you really need to remove one, use
`git rm` and document the reason in a commit message.
