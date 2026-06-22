# RL-DATA-2b — v1.1 Smoke + Quality Gate Assertions

**Date**: 2026-06-22
**Status**: `SMOKE_PASS_GATES_IMPLEMENTED_NO_TRAINING`
**Phase**: RL-DATA-2b (v1.1 smoke + gate assertions, no model training)

## Goal

End-to-end smoke validation of the v1.1 instrumentation
(RL-DATA-2) on a tiny local fixture, and turning the
documented v1.1 data-quality gates (gates 11-18 from the
RL-DATA-1 plan) into code-level analyzer checks.

This phase is **audit / instrumentation only**:

- No RL training.
- No 5k dataset.
- No battle benchmark.
- No production behavior change.
- No scoring, default, or opt-in flag change.
- No WT/Anti-TR behavior change.
- No species-based Magic Bounce deduction.

## Files Changed

- `scripts/analyze/analyze_turn_level_offline_dataset_quality.py`
  (modified)
  - Added `V1_1_GATE_FIELDS` constant — maps each v1.1 field
    to its gate (Gate 12-18).
  - Added `V1_1_BLOCK_FIELDS` constant — fields whose `True`
    value triggers a hard BLOCKED readiness.
  - Added `_check_v1_1_gates(rows, schema_versions)` function —
    computes the v1.1 gate report (schema coverage, field
    coverage, hard blocks, warnings, support-group counts,
    readiness impact).
  - Modified `analyze()` to call `_check_v1_1_gates()` and add
    `v11_gates` to the report. Modified the readiness decision
    to be `BLOCKED` if any v1.1 hard block fires.
  - Updated comments to note v1.1 acceptance.

- `tests/test_v1_1_quality_gates.py` (new, 20 tests)
  - `TestV11GateBasics` (10 tests): clean row, v1.0 n_rows,
    mixed v1.0+v1.1, field coverage 100%, missing field
    coverage, hard blocks for used_species / impossible /
    resurrect, unknown support move surfaced, no v1.1 rows
    returns WARN.
  - `TestV11GateConstants` (3 tests): accepted schemas,
    v1.1 gate fields present, v1.1 block fields.
  - `TestV11AnalyzerEndToEnd` (6 tests): v1.1 smoke analyze,
    v1.0 backward compat, mixed v1.0/v1.1, hard block
    propagates to RL readiness, support group counts,
    CLI end-to-end.
  - `TestV11DryRunCompat` (1 test): dry-run accepts v1.1 rows.

## Smoke Dataset / Fixture

The smoke test uses a **tiny inline fixture** built by the
**real v1.1 builder** (`build_row` in
`showdown_ai/build_turn_level_offline_dataset.py`). This
ensures the smoke is not a synthetic stub — it exercises the
actual v1.1 instrumentation path.

The fixture:
- 1 turn per test (a 1-pair 1-turn case)
- 2 active mons: Incineroar, Politoed
- 2 opp mons: Garchomp, Tyranitar
- Selected action: raindance + fakeout (default), or
  raindance + protect (for the clean-row test)
- Weather: raindance (set by raindance move)
- All v1.1 fields populated by the builder

This is the **smallest possible smoke** — just enough to
verify the v1.1 schema is emitted and the gates are
exercised. No large dataset. No benchmark. No battles run.

## v1.1 Gates Implemented (per RL-DATA-1 plan)

The 8 new v1.1 gates (11-18) are now code-level assertions in
`_check_v1_1_gates()`. Each gate produces a pass/fail
result; hard blocks (Gate 13 used_species, Gate 18 official
provenance) escalate to `BLOCKED` readiness.

### Gate 11 — schema coverage
- Counts v1.0 vs v1.1 vs other schema versions.
- v1.0 and v1.1 are both accepted (per `ACCEPTED_SCHEMAS`).
- Soft warning if other schema versions appear.

### Gate 12 — support instrumentation coverage
- Required v1.1 top-level fields:
  - `unknown_support_move_detected` (bool)
  - `per_candidate_support_classification` (dict)
  - `support_move_distribution` (dict)
- Note: `support_group`, `support_status_from_audit`, and
  `is_support_move` are nested inside
  `per_candidate_support_classification` and are NOT
  separately required at the top level.
- Soft warning if coverage < 50% per field.

### Gate 13 — safety / mechanics
- `used_species_ability_inference` must be `False` (hard block).
- `impossible_target_detected` must not be `True` (hard block).
- `blocked_action_resurrected_by_joint` must not be `True`
  (hard block).
- `revealed_ability_source` should be `"revealed"` or
  `"singleton_deduction"` (soft warning otherwise).

### Gate 14 — Weather / Terrain
- Required v1.1 top-level fields: `weather_current`,
  `terrain_current`, `setter_move_legal`, `setter_move_selected`,
  `type_boost_move_legal`, `type_boost_move_selected`,
  `wt2_relevance_flag`, `wt3_relevance_flag`,
  `wt4_relevance_flag`.
- Soft warning if coverage < 50% per field.

### Gate 15 — reward placeholders explicit
- Required v1.1 fields: `terminal_win_loss`, `turn_delta_hp`,
  `faint_caused`, `faint_suffered`, `sparse_reward_warning`,
  `reward_provenance`, `reward_confidence`.
- Missing values may be `None` or `{}`, but the keys must
  exist (soft warning otherwise).

### Gate 16 — score trace placeholders explicit
- Soft warning only. The v1.1 spec says these keys SHOULD
  exist (`raw_score`, `final_score`, `damage_estimate`,
  `protect_stall_score`, `support_bonus`,
  `safety_block_score`, `selected_rank`,
  `score_component_breakdown`), but they may legitimately
  be `None` if source data is unavailable. v1.1 builder
  does not currently emit these; future RL-DATA-3 phase
  will add them.

### Gate 17 — unknown support move detector
- If `unknown_support_move_detected=True`, the row is
  surfaced as a soft warning (not a hard block per Gate 17
  spec — the detector is for logging, not rejection).
- The `support_move_distribution` always includes all 9
  groups.

### Gate 18 — config / provenance
- `local_only_provenance` must be `True` (hard block if
  `False`).
- `config_hash`, `config_snapshot`, `runtime_mode` are
  expected but may be `None` (soft warning).
- Official-server provenance is rejected (hard block if
  `local_only_provenance=False`).

## Analyzer Result Behavior

The analyzer now reports a `v11_gates` section in the
report. The `readiness_impact` is one of:
- `READY` — no hard blocks, no warnings.
- `WARN` — no hard blocks, but at least one warning
  (e.g., field coverage < 50%, unknown support moves).
- `BLOCKED` — at least one hard block (used_species,
  impossible, blocked_resurrect, or
  local_only_provenance=False).

The RL-readiness decision incorporates the v1.1 impact:
- If v1.1 hard blocks fire, the dataset is `BLOCKED`
  regardless of v1.0 readiness.
- If v1.1 warnings fire, the v1.0 readiness is preserved
  but `v11_impact` is recorded as `WARN`.
- The `rl_readiness` dict includes `v11_impact` and
  `n_v11_hard_blocks` fields.

## v1.0 Compatibility Status

- **v1.0 rows** are still accepted by the analyzer. The
  v1.0 dataset (BI3M2 / RL-5b) is still analyzable.
- v1.0 rows that have NO v1.1 fields are tracked under
  `schema_coverage["v10"]`. The v1.1 readiness is `WARN`
  if v1.0 is the only version present (no v1.1 data to
  verify) — this is expected behavior for legacy data.
- 42 existing `test_build_turn_level_offline_dataset`
  tests pass.
- 20 existing `test_analyze_turn_level_offline_dataset_quality`
  tests pass.
- 42 existing `test_dryrun_turn_level_offline_policy`
  tests pass.

## Dry-run Compatibility Status

The dry-run (`showdown_ai/dryrun_turn_level_offline_policy.py`)
loads JSONL via `_load_dataset(path)` which is schema-agnostic.
v1.1 rows are loaded as a strict superset of v1.0. The
dry-run processes whatever schema is in the input data
(v1.0, v1.1, or mixed). Verified by
`test_v1_1_quality_gates.TestV11DryRunCompat.test_dryrun_loads_v11`.

## Tests Added/Updated

**NEW**: `tests/test_v1_1_quality_gates.py` (20 tests, all pass)

**No modifications** to existing test files.

**No `test_51` touch.**

## Tests Run and Results

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_build_turn_level_offline_dataset.py` | 42 | **PASS** |
| `tests/test_analyze_turn_level_offline_dataset_quality.py` | 20 | **PASS** |
| `tests/test_dryrun_turn_level_offline_policy.py` | 42 | **PASS** |
| `tests/test_turn_level_v1_1_instrumentation.py` | 23 | **PASS** (RL-DATA-2) |
| `tests/test_v1_1_quality_gates.py` | 20 | **PASS** (NEW) |
| **Total RL tests** | **147** | **PASS** |

Sanity tests (unchanged from prior phases):

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_support_move_target_safety.py` | 91 | **PASS** |
| `tests/test_doubles_engine_support_targets.py` | 67 | **PASS** |
| `tests/test_doubles_ability_hard_safety.py` | 86 | **PASS** |
| **Total sanity tests** | **244** | **PASS** |
| **Grand total** | **391** | **PASS** |

## Why RL Training Is Still Not Approved

Per the RL-Readiness Checklist in
`logs/rl_data_1_turn_level_schema_plan.md`, all 13 items
must be true before any training run. The current state:

- [x] Schema plan (RL-DATA-1) — done.
- [x] Instrumentation (RL-DATA-2) — done.
- [x] Gate assertions (RL-DATA-2b, this phase) — done.
- [ ] RL-DATA-3 (5k+ dataset build) — not done.
- [ ] All 18 v1.1 data-quality gates pass on a real 5k+ dataset
  — not done.
- [ ] All 3 baselines evaluated on the 5k+ dataset — not done.
- [ ] Action distribution not collapsed into only double
  attacks — not measured on a real dataset.
- [ ] Support-move distribution covers all 9 groups — not
  measured on a real dataset.
- [ ] No row has `used_species_ability_inference = True` — N/A
  (the builder hardcodes `False`).
- [ ] No row has `impossible_target_detected = True` — N/A.
- [ ] No row has `blocked_action_resurrected_by_joint = True` —
  N/A.
- [ ] User has explicitly authorized Phase 7 — **not done**.
- [ ] AGENTS.md updated to mark Phase 7 as approved — **not
  done**.
- [ ] RL training readiness sign-off committed — not done.

**7 items remain incomplete.** Phase 7 (RL training) is
**not approved** per AGENTS.md and per the 13-item
checklist.

## What Remains Missing

- **Gate 16 implementation**: `damage_estimate`,
  `protect_stall_score`, `support_bonus`,
  `safety_block_score`, `selected_rank`,
  `score_component_breakdown` are not yet emitted by the
  builder. The gate is a soft warning only, but the keys
  don't exist in v1.1 rows. Future RL-DATA-3 phase
  will add these.
- **5k+ dataset**: not built. RL-DATA-3 phase needed.
- **3 baseline comparisons**: majority, current heuristic,
  simple score-based. Not implemented. Future RL-DATA-3
  phase.
- **Action-distribution gate**: the v1.1 schema includes
  `support_move_distribution` (Gate 12 / Gate 17), but the
  `action_distribution` (move / switch / support /
  protect) is not yet aggregated at the battle level. This
  requires a future instrumentation phase.
- **Real v1.1 audit pipeline**: the audit logger
  (`bot_doubles_damage_aware.py`) does not yet emit the
  v1.1 fields at the audit level. Only the builder
  post-processes the v1.0 audit JSONL into v1.1 rows.
  Future RL-DATA-3 phase would instrument the audit
  logger.

## Constraints Respected

- ✅ No RL training
- ✅ No 5k dataset
- ✅ No battle benchmark
- ✅ No production behavior change
- ✅ No scoring/default/behavior change
- ✅ No WT/Anti-TR behavior change
- ✅ No species-based Magic Bounce deduction
- ✅ No new behavior flag
- ✅ No `test_51` touch
- ✅ No commit (per task)
- ✅ No push (per task)
- ✅ v1.0 backward compat preserved (147 existing tests pass)
- ✅ dry-run accepts v1.1 rows
- ✅ analyzer accepts v1.0 and v1.1 rows

## Recommended Next Phase

**RL-DATA-3** — 5k+ dataset build + v1.1 audit-logger
instrumentation. This phase would:

1. Add the v1.1 fields to the audit logger in
   `bot_doubles_damage_aware.py` (not the builder) so that
   future audits natively emit v1.1 fields.
2. Run a 5k+ battle audit with the v1.1 audit logger
   enabled.
3. Build the v1.1 dataset from the new audit.
4. Verify all 18 v1.1 data-quality gates pass.
5. Compute 3 baseline comparisons.
6. **No training.** RL training is still not approved.

`Phase 7` (RL training) is **not approved** per AGENTS.md
and per the 13-item checklist.

## Files in This Phase

- `scripts/analyze/analyze_turn_level_offline_dataset_quality.py`
  (modified)
- `tests/test_v1_1_quality_gates.py` (new, 20 tests)
- `logs/rl_data_2b_v1_1_smoke_and_gates.md` (this file)
