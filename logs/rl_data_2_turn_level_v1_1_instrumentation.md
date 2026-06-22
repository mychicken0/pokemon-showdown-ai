# RL-DATA-2 — turn_rl_v1.1 Instrumentation Implementation

**Date**: 2026-06-22
**Status**: `INSTRUMENTATION_IMPLEMENTED_NO_TRAINING`
**Phase**: RL-DATA-2 (instrumentation only — no model training, no data collection, no benchmark)

## Summary Decision

This phase implements the `turn_rl_v1.1` instrumentation
described in `logs/rl_data_1_turn_level_schema_plan.md`. The
implementation is **instrumentation-only**:

- No production code change (no scoring change, no behavior
  change, no default flip).
- No model training.
- No data collection (no battles run, no benchmarks run).
- No test_51 touch.
- No Anti-Trick-Room behavior change.
- No Weather/Terrain behavior change.
- No species-based Magic Bounce deduction.

The implementation reuses the existing `turn_rl_v1.0` builder
(RL-5), the existing analyzer (RL-6), and the existing
dry-run (RL-7). v1.0 backward compat is preserved: every v1.0
field is still emitted, the v1.0 builder tests still pass, the
v1.0 analyzer still accepts v1.0 rows, the v1.0 dry-run still
runs on v1.0 data.

The v1.1 instrumentation adds new fields **on top of v1.0**,
following the schema defined in `logs/rl_data_1_turn_level_schema_plan.md`.

## Files Changed

- `doubles_engine/support_targets.py` (modified)
  - Added typing imports (`Any, Dict, List, Optional, Tuple`).
  - Added 9 `GROUP_*` constants and 10 `STATUS_*` constants.
  - Added `_KNOWN_SUPPORT_MOVE_INVENTORY` (52 moves mapped to
    (group, status) per SUPPORT-AUDIT-1).
  - Added `_DAMAGE_LIKE_NOT_SUPPORT` (set of damage-move ids).
  - Added `_OPT_IN_FLAGS_BY_STATUS`, `_DEFAULT_ENABLED_BY_STATUS`,
    `_SAFETY_ONLY_BY_STATUS`, `_POSITIVE_STRATEGY_BY_STATUS`
    (per-status lookups).
  - Added `classify_support_move_for_dataset(move_id,
    base_power, category)` — the per-candidate classifier.
  - Added `aggregate_support_distribution(classifications)` —
    the support-group distribution aggregator.
  - Added `_normalize_move_id(move_id)` — internal helper.

- `showdown_ai/build_turn_level_offline_dataset.py` (modified)
  - Added `SCHEMA_VERSION_V1_1 = "turn_rl_v1.1"` constant.
  - Added `SCHEMA_VERSION` comment noting v1.1 is also accepted.
  - Added `_WT2_SETTER_MOVE_IDS` (9 setter move ids).
  - Added `_TYPE_BOOST_MOVE_IDS` (~25 type-boost move ids).
  - Added `_support_targets_classify()` (lazy import).
  - Added `_normalize_v1_1_move_id()`.
  - Added `_extract_v1_1_metadata()` — config_hash, format,
    team_id, runtime_mode, reward placeholders.
  - Added `_extract_v1_1_weather_terrain()` — weather_current,
    terrain_current, setter_move_legal/selected, type-boost,
    WT-2/3/4 relevance flags.
  - Added `_extract_v1_1_safety_fields()` — block reasons,
    revealed_ability_source, used_species_ability_inference
    (always `False`), impossible_target_detected,
    blocked_action_resurrected_by_joint.
  - Added `_extract_v1_1_support_classification()` —
    per-candidate classification, support distribution, unknown
    flag.
  - Added `_build_v1_1_fields()` — combines all of the above.
  - Updated `build_row()` to use `SCHEMA_VERSION_V1_1` and call
    `_build_v1_1_fields()` after the v1.0 optional fields.

- `scripts/analyze/analyze_turn_level_offline_dataset_quality.py`
  (modified)
  - Added `ACCEPTED_SCHEMAS = ("turn_rl_v1.0", "turn_rl_v1.1")`
    constant.
  - Updated comment to note v1.1 is also accepted.
  - **No behavior change** — the analyzer already tracks
    schema versions in a `Counter`; v1.0 and v1.1 rows are
    both accepted without rejection.

- `showdown_ai/dryrun_turn_level_offline_policy.py` (modified)
  - Updated `SCHEMA_VERSION` comment to note v1.1 is also
    accepted.
  - **No behavior change** — the dry-run already operates
    on whatever schema is in the input data; v1.0 and v1.1
    rows are both processed.

- `tests/test_turn_level_v1_1_instrumentation.py` (new, 23 tests)
  - `TestClassifierBasics` (9 tests): known moves map to
    correct group/status, damaging moves are not support,
    unknown moves are tagged correctly, normalization
    works.
  - `TestAggregateDistribution` (3 tests): empty list gives
    all-zero counts, counts are correct, damaging moves
    excluded.
  - `TestV11SchemaRow` (8 tests): schema version is v1.1,
    metadata fields present, weather/terrain fields present,
    setter detection works, safety fields present and
    `used_species_ability_inference = False`, reward fields
    present, support classification present, v1.0 fields
    preserved.
  - `TestUnknownSupportMoveDetector` (2 tests): unknown move
    triggers flag, all-known moves don't trigger.
  - `TestV11DefaultsWhenSourceMissing` (1 test): minimal turn
    has safe defaults for all v1.1 fields.

## v1.1 Fields Implemented

Per the RL-DATA-1 schema plan, the following v1.1 fields
are now emitted by `build_row()`:

### 1. Metadata / provenance

| field | value | status |
|---|---|---|
| `config_hash` | from `turn.config_hash` (or `None`) | NEW |
| `config_snapshot` | from `turn.config_snapshot` (or `{}`) | NEW |
| `local_only_provenance` | always `True` | NEW |
| `format` | from `turn.format` or `row_battle.format` | NEW |
| `team_id` | from `turn.team_id` or `row_battle.team_id` | NEW |
| `opponent_team_id` | from `turn.opponent_team_id` or `row_battle.opponent_team_id` | NEW |
| `runtime_mode` | from `turn.runtime_mode` | NEW |
| `terminal_win_loss` | always `None` in v1.1 (filled from episode) | NEW |
| `turn_delta_hp` | from `turn.turn_delta_hp` (or `{}`) | NEW |
| `faint_caused` | from `turn.faint_caused` (or `None`) | NEW |
| `faint_suffered` | from `turn.faint_suffered` (or `None`) | NEW |
| `delayed_reward_placeholder` | always `0.0` | NEW |
| `sparse_reward_warning` | always `True` | NEW |
| `reward_provenance` | always `"terminal_only"` | NEW |
| `reward_confidence` | always `1.0` | NEW |

### 2. Weather / Terrain

| field | value | status |
|---|---|---|
| `weather_current` | from `state_snapshot.weather` | NEW |
| `terrain_current` | from `state_snapshot.fields` | NEW |
| `setter_move_legal` | list of setter move ids in legal actions | NEW |
| `setter_move_selected` | list of setter move ids in selected | NEW |
| `setter_move_raw_score` | dict (or `None` if not available) | NEW |
| `type_boost_move_legal` | list of type-boost move ids in legal | NEW |
| `type_boost_move_selected` | list of type-boost move ids in selected | NEW |
| `type_boost_applied` | always `[]` (needs execution-time data) | NEW |
| `wt2_relevance_flag` | `True` if any setter move was legal | NEW |
| `wt3_relevance_flag` | `True` if any type-boost move was legal | NEW |
| `wt4_relevance_flag` | `True` if any setter move was selected | NEW |

### 3. Safety / mechanics

| field | value | status |
|---|---|---|
| `block_reason_wrong_side` | from `turn.block_reason_wrong_side` (or `None`) | NEW |
| `block_reason_narrow_ally_heal` | from `turn.block_reason_narrow_ally_heal` (or `None`) | NEW |
| `block_reason_broad_support_target` | from `turn.block_reason_broad_support_target` (or `None`) | NEW |
| `block_reason_ability_hard_safety` | from `turn.block_reason_ability_hard_safety` (or `None`) | NEW |
| `revealed_ability_source` | from `turn.revealed_ability_source` (default `"revealed"`) | NEW |
| `used_species_ability_inference` | always `False` (mandatory assertion) | NEW |
| `impossible_target_detected` | from `turn.impossible_target_detected` (default `False`) | NEW |
| `blocked_action_resurrected_by_joint` | from `turn.blocked_action_resurrected_by_joint` (default `False`) | NEW |

### 4. Support-move classification

| field | value | status |
|---|---|---|
| `per_candidate_support_classification` | dict mapping move_id -> classification | NEW |
| `support_move_distribution` | dict mapping group -> count (all 9 groups) | NEW |
| `unknown_support_move_detected` | `True` if any candidate is unknown | NEW |

The classification is done by
`classify_support_move_for_dataset(move_id, base_power, category)`
which uses the SUPPORT-AUDIT-1 inventory and
`_DAMAGE_LIKE_NOT_SUPPORT` set.

## Fields Still Missing / Unavailable

These v1.1 fields are defined in the schema but require a
future RL-DATA-3 instrumentation phase to populate:

- `damage_estimate` per action — requires per-action damage
  recording in the bot.
- `protect_stall_score` per action — requires per-action
  protect scoring recording in the bot.
- `support_bonus` per action — requires per-action positive
  support-bonus recording (currently no positive support
  bonus exists, see SUPPORT-AUDIT-1).
- `safety_block_score` per action — requires per-action block
  score recording.
- `selected_rank` — requires rank calculation against all
  candidates.
- `score_component_breakdown` — requires per-component
  score recording.
- `v4a_raw_scores_slot0/1` were `None` in BI3M2 (RL-5b root
  cause: BEHAVIOR-18 fields added after BI3M2 source was
  generated).
- `config_hash` / `config_snapshot` — requires the audit
  logger to record the bot's `DoublesDamageAwareConfig`.

All fields that are `None` or `{}` or `False` are explicitly
safe defaults. The analyzer must report missing optional
fields as warnings but must NOT reject the dataset.

## Tests Run and Results

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_build_turn_level_offline_dataset.py` | 42 | **PASS** (v1.0 builder still works) |
| `tests/test_analyze_turn_level_offline_dataset_quality.py` | 20 | **PASS** (v1.0 analyzer still works) |
| `tests/test_dryrun_turn_level_offline_policy.py` | 42 | **PASS** (v1.0 dry-run still works) |
| `tests/test_turn_level_v1_1_instrumentation.py` | 23 | **PASS** (NEW v1.1 tests) |
| **Total** | **127** | **PASS** |

Sanity tests (not part of RL suite, but worth running):

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_support_move_target_safety.py` | 91 | **PASS** (broad + narrow safety unchanged) |
| `tests/test_doubles_engine_support_targets.py` | 67 | **PASS** (engine helpers unchanged) |
| **Total** | **285** | **PASS** |

## Backward Compat Status

- **Builder**: produces v1.1 rows. The v1.0 `SCHEMA_VERSION`
  constant is preserved (with a comment) so any existing
  reference to it still works. The new `SCHEMA_VERSION_V1_1`
  constant is the actual value emitted. v1.0 rows that pass
  through the new builder become v1.1 rows; the v1.0 fields
  are still present.
- **Analyzer**: tracks schema versions in a `Counter` and
  does NOT reject any version. v1.0 and v1.1 rows are both
  processed. The `ACCEPTED_SCHEMAS` constant is added for
  documentation; the analyzer behavior is unchanged.
- **Dry-run**: operates on whatever schema is in the input
  data. v1.0 and v1.1 rows are both processed. The
  `SCHEMA_VERSION` comment is updated.
- **Existing v1.0 data**: 42 fixture tests in
  `test_build_turn_level_offline_dataset.py` still pass. The
  v1.0 BI3M2 dataset is still analyzable.

## v1.1 Data Quality Gates (per RL-DATA-1 plan)

The 18 gates defined in the RL-DATA-1 plan are **not yet
implemented in code** — they are documented in the plan. The
gates will need a future RL-DATA-3 (dataset build) phase to
implement as code-level assertions in the analyzer and
builder. For now, the analyzer continues to run the existing
10 v1.0 gates; the v1.1 gates are pending implementation.

The 8 new v1.1 gates that are NOT yet code-level:

11. No species-based ability inference (assertion in
    `used_species_ability_inference`).
12. No impossible target (assertion in
    `impossible_target_detected`).
13. No blocked-action resurrection (assertion in
    `blocked_action_resurrected_by_joint`).
14. Support-move distribution not collapsed (assertion in
    `support_move_distribution`).
15. Revealed ability only (assertion in
    `revealed_ability_source`).
16. Config default invariants (assertion in row's flag snapshot).
17. Action distribution not collapsed into only double
    attacks (assertion in `action_distribution`).
18. WT-2 / WT-3 / WT-4 coverage (assertion in
    `setter_move_legal` / `type_boost_move_legal`).

These are recorded as `None` / `False` / safe defaults in v1.1
and will be wired as code-level assertions in a future phase.

## Constraints Respected

- ✅ No RL training
- ✅ No large dataset collection
- ✅ No battle runs (audit/instrumentation only)
- ✅ No benchmark
- ✅ No production behavior change (no scoring, no default
  flip, no opt-in flag flipped)
- ✅ No Weather/Terrain behavior change (WT-2 conclusion
  preserved)
- ✅ No Anti-Trick-Room behavior change
- ✅ No species-based Magic Bounce deduction
- ✅ No new behavior flag added
- ✅ No `test_51` touch
- ✅ No official Pokémon Showdown servers
- ✅ No commit (per task)
- ✅ No push (per task)
- ✅ v1.0 backward compat preserved (127 existing tests pass)

## Status of "TODO" from prior phases

- **RL-8 closeout**: `PIPELINE_WORKS / TRAINING_NOT_APPROVED`.
  v1.1 instrumentation does not start training.
- **SUPPORT-AUDIT-1**: 9 support-move groups classified. v1.1
  uses the same 9 groups + 10 statuses.
- **RL-DATA-1**: schema plan. v1.1 instrumentation
  implements the plan.
- **Phase 7 (RL training)**: still not approved per AGENTS.md.

## Files in This Phase

- `doubles_engine/support_targets.py` (modified)
- `showdown_ai/build_turn_level_offline_dataset.py` (modified)
- `scripts/analyze/analyze_turn_level_offline_dataset_quality.py`
  (modified)
- `showdown_ai/dryrun_turn_level_offline_policy.py` (modified)
- `tests/test_turn_level_v1_1_instrumentation.py` (new, 23 tests)
- `logs/rl_data_2_turn_level_v1_1_instrumentation.md` (this file)

## Recommended Next Phase

**RL-DATA-3**: 5k+ dataset build + v1.1 data-quality gates
implementation. This phase would:

1. Run the existing builder on a v1.1 instrumented audit
   (requires a future instrumentation phase to add the
   v1.1 fields to the audit logger in
   `bot_doubles_damage_aware.py`).
2. Implement the 8 new v1.1 data-quality gates as code-level
   assertions in the analyzer.
3. Verify the v1.1 dataset passes all 18 gates.
4. Document the v1.1 dataset's gate status in a
   `turn_rl_v1.1_dataset_status.md` log.
5. **No training.** RL training is still not approved per
   RL-8 and AGENTS.md.

`Phase 7` (RL training) is **not approved** per RL-8
closeout and AGENTS.md.
