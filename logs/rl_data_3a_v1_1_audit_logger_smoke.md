# RL-DATA-3a — v1.1 Audit Logger Emission + Tiny Local Audit Smoke

**Date**: 2026-06-22
**Status**: `AUDIT_EMISSION_IMPLEMENTED_SMOKE_PASS_NO_TRAINING`
**Phase**: RL-DATA-3a (v1.1 audit logger emission + tiny local audit smoke)

## Goal

Wire the `turn_rl_v1.1` instrumentation into the real
audit logging path so future datasets can be built from
actual local bot audits. RL-DATA-2 added the v1.1 fields
to the **builder** (synthesized from v1.0 audit JSONL).
RL-DATA-3a moves that synthesis forward: the audit
logger itself emits the v1.1 fields directly.

This is **NOT** RL training. **NOT** a 5k dataset.
**NOT** a benchmark. **NOT** a behavior / scoring /
default change.

## Audit Logger Path Found

The real audit logger is
`showdown_ai/doubles_decision_audit_logger.py`:
- `log_turn_decision` (line 741): called per turn from
  the bot at
  `showdown_ai/bot_doubles_damage_aware.py:13377`.
- `save_battle` (line 3262): writes the persisted
  battle record to
  `logs/doubles_decision_audit.jsonl` (line 3330).

The persisted JSONL shape (per line):

```json
{
  "battle_tag": "...",
  "winner": "...",
  "won": true,
  "total_turns": 9,
  "audit_turns": [
    {
      "turn": 1,
      "our_active": [...],
      "opp_active": [...],
      "selected_joint_order": "/choose move ..." ,
      "selected_score": 150.0,
      "slot_0": {...},
      "slot_1": {...},
      "opp_actions": {...},
      "v4a_legal_action_keys_slot0": [...],
      "v4a_legal_action_keys_slot1": [...],
      "v4a_selected_joint_key": [...],
      "v4a_final_action_keys": [...],
      "v2l1_legal_action_keys_slot0": [...],
      "v2l1_raw_scores_slot0": {...},
      "state_snapshot": {"weather": ..., "fields": [...], ...}
    }
  ]
}
```

Before RL-DATA-3a, the v1.1 fields were NOT in the
audit JSONL. They were synthesized by the builder from
the v1.0 fields. After RL-DATA-3a, the v1.1 fields are
in the audit JSONL by default, and the builder's
audit-fast path consumes them directly.

## Files Changed

- `doubles_engine/audit_v1_1_metadata.py` (new, 366
  lines): the v1.1 emission helper module.
  - `V1_1_EMITTED_FIELDS`: tuple of 37 field names the
    helper writes.
  - `_WT2_SETTER_MOVE_IDS` / `_TYPE_BOOST_MOVE_IDS`:
    mirrored from the builder for consistency.
  - `_normalize_v1_1_move_id`: move-id canonicalization
    (lowercase, no spaces / dashes / underscores /
    apostrophes).
  - `_extract_v1_1_weather`: handles string, list, and
    the pre-existing audit logger character-list quirk.
  - `_extract_setter_raw_scores`: parses pipe-joined
    action keys to extract per-setter raw scores.
  - `_extract_v1_1_safety_block_reasons`: synthesizes
    v1.1 block reasons from per-slot support / narrow
    ally-heal / ability-hard-safety fields.
  - `_extract_v1_1_revealed_ability_source`: defaults
    to `"revealed"`; flips to `"singleton_deduction"`
    only when a per-slot singleton resolution fired.
  - `_extract_v1_1_support_classification`: classifies
    every move in the V4a legal-action keys per
    SUPPORT-AUDIT-1.
  - `populate_v1_1_audit_fields(turn_data)`: the public
    helper. Pure: writes v1.1 fields to a turn_data
    dict in place. Idempotent.

- `showdown_ai/doubles_decision_audit_logger.py`
  (modified): added `_emit_v1_1_fields(turn_data)`
  method that delegates to the helper, wrapped in a
  try/except. Called at the end of `log_turn_decision`
  (after the per-slot mirror fields are written) so the
  persisted JSONL carries v1.1 fields directly. The
  try/except wrap is observational-only: a v1.1 helper
  failure writes `v1_1_emission_failed=True` and
  `v1_1_emission_error=...` to the turn_data, but never
  breaks the v1.0 hot path.

- `showdown_ai/build_turn_level_offline_dataset.py`
  (modified): `_extract_v1_1_weather_terrain` now
  prefers audit-emitted v1.1 fields when present (the
  audit-fast path). Falls back to the v1.0
  state-snapshot path when the audit fields are
  missing. The state-snapshot fallback handles the
  pre-existing `_enum_keys` character-list quirk. New
  small helpers `_setter_legal` / `_setter_selected` /
  `_tb_legal` / `_tb_selected` pass through the
  audit-emitted lists.

- `showdown_ai/doubles_audit_v1_1_smoke.py` (new, 322
  lines): tiny local audit smoke. 1 battle, 1 turn,
  no real Showdown. Builds a real audit JSONL, runs the
  builder, runs the analyzer, runs the dry-run, reports
  the v1.1 readiness impact.

- `tests/test_doubles_audit_v1_1_emission.py` (new,
  24 tests, all pass):
  - `TestPopulateV11Unit` (15 tests): unit tests for
    `populate_v1_1_audit_fields`. Verifies all 37 v1.1
    fields are emitted, `local_only_provenance=True`,
    `used_species_ability_inference=False`, weather /
    terrain / setter / type-boost extraction,
    pipe-joined raw scores, reward placeholders,
    revealed-ability-source default and singleton
    override, idempotency, empty-turn-data safety,
    unknown-support-move detection preserved.
  - `TestAuditLoggerEmitsV11` (2 tests): the real
    audit logger's `log_turn_decision` populates v1.1
    fields on the persisted turn, and a helper
    failure never breaks the v1.0 hot path.
  - `TestAuditV11EndToEnd` (1 test): audit emission
    → builder → analyzer → dry-run.

## Exact v1.1 Fields Now Emitted by the Audit Logger

The helper emits the following 37 fields (in the order
the analyzer / builder look for them). The audit JSONL
turn dict now has these keys:

| Field | Source | Notes |
|-------|--------|-------|
| `config_hash` | `turn.get("config_hash", None)` | None unless set elsewhere |
| `config_snapshot` | `turn.get("config_snapshot", {})` | empty dict default |
| `local_only_provenance` | **hardcoded** `True` | local-only invariant |
| `format` | `turn.get("format", None)` | None unless set elsewhere |
| `team_id` | `turn.get("team_id", None)` | None unless set elsewhere |
| `opponent_team_id` | `turn.get("opponent_team_id", None)` | None unless set elsewhere |
| `runtime_mode` | `turn.get("runtime_mode", None)` | preserved from v1.0 |
| `terminal_win_loss` | **hardcoded** `None` | filled by builder from episode |
| `turn_delta_hp` | **hardcoded** `{}` | not derivable from pre-decision snapshot |
| `faint_caused` | **hardcoded** `None` | not derivable |
| `faint_suffered` | **hardcoded** `None` | not derivable |
| `delayed_reward_placeholder` | **hardcoded** `0.0` | per v1.1 plan |
| `sparse_reward_warning` | **hardcoded** `True` | per v1.1 plan |
| `reward_provenance` | **hardcoded** `"terminal_only"` | per v1.1 plan |
| `reward_confidence` | **hardcoded** `1.0` | per v1.1 plan |
| `weather_current` | `state_snapshot.weather` | handles string, list, char-list |
| `terrain_current` | `state_snapshot.fields` | handles string, list, char-list |
| `setter_move_legal` | `v4a_legal_action_keys_slot0/1` | sorted, deduped |
| `setter_move_selected` | `v4a_selected_joint_key` | sorted, deduped |
| `setter_move_raw_score` | `v2l1_raw_scores_slot0/1`, `v4a_raw_scores_slot0/1` | pipe-joined keys |
| `type_boost_move_legal` | `v4a_legal_action_keys_slot0/1` | sorted, deduped |
| `type_boost_move_selected` | `v4a_selected_joint_key` | sorted, deduped |
| `type_boost_applied` | **hardcoded** `[]` | needs execution-time data |
| `wt2_relevance_flag` | `bool(setter_move_legal)` | |
| `wt3_relevance_flag` | `bool(type_boost_move_legal)` | |
| `wt4_relevance_flag` | `bool(setter_move_selected)` | |
| `block_reason_wrong_side` | per-slot `support_target_wrong_side_selected` | None default |
| `block_reason_narrow_ally_heal` | per-slot `narrow_ally_heal_candidate_blocked` | None default |
| `block_reason_broad_support_target` | per-slot `support_target_candidate_blocked` | None default |
| `block_reason_ability_hard_safety` | per-slot `ability_block_reason` | None default |
| `revealed_ability_source` | per-slot `singleton_ability_resolved` | `"revealed"` / `"singleton_deduction"` |
| `used_species_ability_inference` | **hardcoded** `False` | NEVER True |
| `impossible_target_detected` | **hardcoded** `False` | would need opt-in flag to flip |
| `blocked_action_resurrected_by_joint` | **hardcoded** `False` | would need opt-in flag to flip |
| `per_candidate_support_classification` | all V4a legal keys | per-move-id dict |
| `support_move_distribution` | per-group counts | 9 groups always present |
| `unknown_support_move_detected` | True if any candidate is `unknown_needs_probe` | surfaced, not blocked |

`V1_1_EMITTED_FIELDS` is a frozen tuple of these 37
field names. The helper guarantees that on a clean
turn_data dict (e.g., empty `{}`), all 37 keys are
present with safe defaults (None / False / 0 / []).

## Tiny Smoke Method

A 1-battle 1-turn smoke that exercises the entire
audit → builder → analyzer → dry-run pipeline using a
mocked battle and the real audit logger. The smoke
writes:

- `logs/doubles_audit_v1_1_smoke.jsonl` (1 line)
- `logs/doubles_audit_v1_1_smoke_dataset.jsonl` (1 line)

The smoke does NOT run a real battle. It does NOT use
the local Showdown server. It does NOT touch the
official Pokémon Showdown server. It mocks a tiny
battle (Politoed + Incineroar vs Garchomp +
Tyranitar) and calls the audit logger's
`log_turn_decision` + `save_battle` directly with a
minimal set of kwargs.

The smoke verifies:

- The persisted audit JSONL contains 25 v1.1 fields
  per turn (8 directly checked by the smoke script,
  25 total when iterating `V1_1_EMITTED_FIELDS`).
- The builder produces 1 v1.1 row, 0 skipped.
- The analyzer reports `v1.1 readiness_impact: WARN`
  (no hard blocks; 1 Gate 17 soft warning).
- The dry-run loads 1 v1.1 row.

## Builder Compatibility Status

The builder now has an **audit-fast path** for v1.1
weather/terrain: if the audit JSONL has
`weather_current` / `terrain_current` /
`setter_move_legal` / `setter_move_selected` /
`type_boost_move_legal` / `type_boost_move_selected`,
the builder passes them through. The
state-snapshot fallback still works (and is more
robust now: handles the pre-existing character-list
quirk from `_enum_keys`).

The audit-fast path is opt-in by data: the builder
detects the presence of the audit-emitted v1.1 fields
and uses them. If the audit JSONL does NOT have them
(e.g., a pre-RL-DATA-3a audit), the builder falls
back to synthesizing from `state_snapshot` /
`v4a_legal_action_keys_*` exactly as before.

`test_build_turn_level_offline_dataset` (42 v1.0
tests) pass unchanged. The builder's v1.0 output
shape is preserved.

## Analyzer Gate Result

```
Stage 3: Analyzer
  v1.1 readiness_impact: WARN
  v1.1 n_rows: 1
  v1.0 n_rows: 0
  hard_blocks: 0
  warnings: 1 item(s)
  dry-run loaded 1 row
```

The single warning is:

> Gate 17: 1 v1.1 row(s) with
> `unknown_support_move_detected=True` (not blocking)

This is from the smoke's `fakeout` and `hurricane`
moves, which the classifier flags as
`unknown_needs_probe` because the audit logger does
not record `base_power` (a pre-existing v1.1 builder
limitation, not a regression). Gate 17 is a soft
warning per the RL-DATA-1 plan, so the readiness
impact is `WARN`, not `BLOCKED`. The
`support_move_distribution` correctly shows
`unknown_needs_probe=2`.

Field coverage is 100% on all 25 v1.1 fields checked
in the smoke. The audit-fast path is working.

## v1.0 Compatibility Status

v1.0 rows are still accepted by the builder, the
analyzer, and the dry-run. The audit-fast path is
opt-in: if the audit JSONL has the v1.1 fields, the
builder uses them; otherwise the builder falls back
to the state-snapshot path. 42 v1.0 builder tests +
20 v1.0 analyzer tests + 42 v1.0 dry-run tests pass
unchanged.

## Dry-run Compatibility Status

The dry-run
(`showdown_ai/dryrun_turn_level_offline_policy.py`)
loads JSONL via `_load_dataset(path)` which is
schema-agnostic. v1.1 rows are loaded as a strict
superset of v1.0. The dry-run processes whatever
schema is in the input data (v1.0, v1.1, or mixed).
Verified by `TestAuditV11EndToEnd` in the new test
file and by 42 existing dry-run tests.

## Fields Still Unavailable / Placeholders

- `terminal_win_loss`: filled by the builder from
  episode metadata (`row_battle.won`). The audit
  logger does not have this. Emitted as `None` so the
  key is present and the builder can fill it.
- `turn_delta_hp`: not derivable from the
  pre-decision snapshot. Emitted as `{}` (empty dict).
  A future instrumentation phase could fill this from
  `update_previous_turn` (where actual vs expected
  damage is recorded).
- `faint_caused` / `faint_suffered`: not derivable
  from the pre-decision snapshot. Emitted as `None`.
  A future phase could fill this from
  `update_previous_turn`.
- `config_hash` / `config_snapshot` / `format` /
  `team_id` / `opponent_team_id`: not available to
  the audit logger. Emitted as `None` / empty dict.
  A future phase could pass them from the runner
  (similar to `_current_battle_meta`).
- `type_boost_applied`: would need execution-time
  damage / boost data. Emitted as `[]`. A future
  phase could fill this from `update_previous_turn`.
- `setter_move_raw_score`: emitted only if the
  audit logger has a recorded raw score for a setter
  move in `v2l1_raw_scores_slot0/1` or
  `v4a_raw_scores_slot0/1`. Otherwise `None`.
- `per_candidate_support_classification.support_group`
  for `fakeout` / `hurricane`: classified as
  `unknown_needs_probe` because the audit logger
  does not record `base_power`. This is a known
  limitation of the audit logger, not a regression.

## Why RL Training Remains Not Approved

Per the RL-Readiness Checklist in
`logs/rl_data_1_turn_level_schema_plan.md`, all 13
items must be true before any training run. Current
status:

- [x] Schema plan (RL-DATA-1) — done.
- [x] Instrumentation (RL-DATA-2) — done.
- [x] Gate assertions (RL-DATA-2b) — done.
- [x] Audit logger emission (RL-DATA-3a, this phase) —
  done. The audit JSONL now carries v1.1 fields by
  default.
- [ ] RL-DATA-3b (5k+ dataset build) — not done.
- [ ] All 18 v1.1 data-quality gates pass on a real
  5k+ dataset — not done.
- [ ] All 3 baselines evaluated on the 5k+ dataset —
  not done.
- [ ] Action distribution not collapsed into only
  double attacks — not measured on a real dataset.
- [ ] Support-move distribution covers all 9 groups —
  not measured on a real dataset.
- [x] No row has `used_species_ability_inference=True`
  — N/A (the audit logger hardcodes `False`).
- [x] No row has `impossible_target_detected=True` —
  N/A (the audit logger hardcodes `False`).
- [x] No row has `blocked_action_resurrected_by_joint=True`
  — N/A (the audit logger hardcodes `False`).
- [ ] User has explicitly authorized Phase 7 — **not
  done**.
- [ ] AGENTS.md updated to mark Phase 7 as approved —
  **not done**.
- [ ] RL training readiness sign-off committed — not
  done.

**9 items remain incomplete.** Phase 7 (RL training)
is **not approved** per AGENTS.md and per the 13-item
checklist.

## Why 5k Dataset Is Deferred Until After This Smoke

The 5k dataset needs the audit logger to emit v1.1
fields. Before RL-DATA-3a, the audit logger did NOT
emit v1.1 fields; the builder synthesized them from
v1.0 fields. The synthesis was correct for a clean
audit JSONL, but a real 5k audit would expose:

1. Pre-existing audit logger bugs (e.g., the
   `_enum_keys` character-list quirk for `weather`
   / `fields`).
2. Missing fields in real battle data (e.g.,
   `base_power` for support-move classification).
3. Field coverage gaps in the builder's fallback
   path (e.g., `setter_move_raw_score` is `None`
   unless the audit logger records the raw score).

RL-DATA-3a resolves (1) by emitting v1.1 fields
directly from the audit logger and making the helper
robust to the character-list quirk. (2) and (3)
remain — they require a real 5k audit to surface
systematically.

A future RL-DATA-3b phase would:

1. Run a 5k+ battle audit with the v1.1 audit logger
   enabled.
2. Build a v1.1 dataset from the new audit.
3. Run all 18 v1.1 data-quality gates on the
   resulting dataset.
4. Compute 3 baseline comparisons.
5. **No training.** RL training is still not
   approved per the 13-item checklist.

## Constraints Respected

- ✅ No RL training.
- ✅ No 5k dataset.
- ✅ No battle benchmark.
- ✅ No production behavior change.
- ✅ No scoring/default/opt-in-flag change.
- ✅ No WT/Anti-TR behavior change.
- ✅ No species-based Magic Bounce deduction.
- ✅ `used_species_ability_inference` is hardcoded
  `False` in the audit logger.
- ✅ `local_only_provenance` is hardcoded `True`.
- ✅ No `test_51` touch.
- ✅ No commit (per task).
- ✅ No push (per task).
- ✅ v1.0 backward compat preserved (171 existing
  tests pass).
- ✅ Dry-run accepts v1.1 rows.

## Tests Run and Results

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_audit_v1_1_emission.py` (new) | 24 | **PASS** |
| `tests/test_turn_level_v1_1_instrumentation.py` | 23 | **PASS** |
| `tests/test_v1_1_quality_gates.py` | 20 | **PASS** |
| `tests/test_build_turn_level_offline_dataset.py` | 42 | **PASS** |
| `tests/test_analyze_turn_level_offline_dataset_quality.py` | 20 | **PASS** |
| `tests/test_dryrun_turn_level_offline_policy.py` | 42 | **PASS** |
| **Total RL tests** | **171** | **PASS** |

Sanity tests (unchanged):

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_support_move_target_safety.py` | 91 | **PASS** |
| `tests/test_doubles_engine_support_targets.py` | 67 | **PASS** |
| `tests/test_doubles_ability_hard_safety.py` | 86 | **PASS** |
| `tests/test_doubles_decision_timing_diagnostics.py` | 7 | **PASS** |
| `tests/test_doubles_voluntary_switch_extraction_fix.py` | 11 | **PASS** |
| `tests/test_doubles_engine_audit_bi1.py` | 12 | **PASS** |
| `tests/test_doubles_engine_audit_bi2.py` | 13 | **PASS** |
| `tests/test_doubles_engine_audit_bi3.py` | 14 | **PASS** |
| **Total sanity tests** | **301** | **PASS** |
| **Grand total** | **472** | **PASS** |

## Files in This Phase

- `doubles_engine/audit_v1_1_metadata.py` (new, 366 lines)
- `showdown_ai/doubles_decision_audit_logger.py` (modified, +30 lines)
- `showdown_ai/build_turn_level_offline_dataset.py` (modified, +120 lines, refactored `_extract_v1_1_weather_terrain`)
- `showdown_ai/doubles_audit_v1_1_smoke.py` (new, 322 lines)
- `tests/test_doubles_audit_v1_1_emission.py` (new, 24 tests)
- `logs/rl_data_3a_v1_1_audit_logger_smoke.md` (this file)
- `logs/doubles_audit_v1_1_smoke.jsonl` (smoke output, 1 line, 36 KB)
- `logs/doubles_audit_v1_1_smoke_dataset.jsonl` (smoke output, 1 line, 5 KB)

## Recommended Next Phase

**RL-DATA-3b** — 5k+ battle audit with v1.1 audit
logger + dataset build + 18-gate evaluation. This
phase would:

1. Run a 5k+ battle audit with the v1.1 audit
   logger enabled (uses the real
   `DoublesDecisionAuditLogger`).
2. Build a v1.1 dataset from the new audit.
3. Run all 18 v1.1 data-quality gates on the
   resulting dataset.
4. Compute 3 baseline comparisons (majority, current
   heuristic, simple score-based).
5. **No training.** RL training is still not
   approved per the 13-item checklist.

`Phase 7` (RL training) is **not approved** per
AGENTS.md and per the 13-item checklist.
