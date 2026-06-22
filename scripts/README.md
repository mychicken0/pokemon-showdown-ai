# scripts/

**Helper scripts** - All non-test, non-bot utility scripts.

## What goes here (and where)

### `scripts/analyze/`
One-off analysis scripts (40 files at root):
- `analyze_*.py` - Inspect logs, compute stats, validate hypotheses
- Examples: `analyze_logs.py`, `analyze_doubles_champion.py`, `analyze_setup4_bonus_sweep.py`

### `scripts/inspect/`
Battle / case inspection scripts:
- `inspect_*.py` - Drill into specific battle cases
- Examples: `inspect_ability_hard_safety_cases.py`, `inspect_doubles_audit_battle.py`

### `scripts/eval/`
Policy evaluation scripts:
- `eval_*.py` - Evaluate bot policies on offline datasets
- Examples: `eval_vgc2026_phaseV2e_policies.py`, `eval_vgc2026_policies_offline.py`

### `scripts/dryrun/`
Dry-run / rehearsal scripts (no real battles):
- `dryrun_*.py` - Test scoring logic in isolation
- Examples: `dryrun_turn_level_offline_policy.py`, `run_intent_policy_dryrun.py`

### `scripts/check/`
Sanity check / validation scripts:
- `check_*.py` - Verify format/data correctness
- Examples: `check_doubles_formats.py`, `check_random_set_coverage.py`

### `scripts/diagnose/`
Diagnostic scripts (debugging helpers):
- `diagnose_*.py` - Diagnose specific issues
- Examples: `diagnose_protect_usage.py`

### `scripts/fix/`
One-off data fix scripts:
- `fix_*.py` - Repair / patch data files
- Examples: `fix_detailed_moves.py`, `fix_rk9_moves_final.py`

### `scripts/build/`
Dataset / build scripts (already in scripts/):
- `build_planner_dataset.py`
- `generate_intent_dashboard.py`

### `scripts/export/`
Data export scripts:
- `export_*.py` - Export data to various formats
- Examples: `export_canonical.py`

### `scripts/` (root)
Ad-hoc scripts not fitting other categories:
- `batch_fetch.py`, `fetcher.py` - Network / data fetching
- `enrich_source_urls.py` - Data enrichment
- `audit_doubles_narrow_ally_heal_paired_638d1.py` - One-off audit
- Existing `start_local_showdown.sh` - Server startup
- Existing `v2l1_smoke.py` - Smoke test
- Existing `run_mixed_stability_test.py` - Mixed stability test

## Migration plan (NOT YET MOVED)

Currently the candidate files are still at the project root.
This folder structure is reserved for the future move. The user
opted for "create folders + placeholders only" - safe approach.

## When ready to migrate

```bash
# Example (run manually when ready):
git mv analyze_logs.py scripts/analyze/
git mv inspect_ability_hard_safety_cases.py scripts/inspect/
git mv eval_vgc2026_policies_offline.py scripts/eval/
# ... etc
```

After moving, update:
- `Makefile` or test runner config (if any)
- Any CI/CD config that references script paths
- Documentation that references script paths
