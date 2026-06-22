# RL-DATA-3a.2 — Live Move-Object Metadata Override Wiring

**Date**: 2026-06-22
**Status**: `LIVE_OVERRIDE_WIRED_SMOKE_READY_NO_TRAINING`
**Phase**: RL-DATA-3a.2 (live move-object metadata override wiring)

## Goal

Wire live poke-env `Move` object metadata from the
real decision path into the v1.1 audit logger, so
future audit datasets do not rely mainly on the
static fallback move metadata table. RL-DATA-3a.1
fixed the false `unknown_needs_probe` tag for known
damaging moves (e.g., `fakeout`, `hurricane`) by
adding a static fallback table. RL-DATA-3a.2 wires
the live override path: the bot's `choose_move`
call site can now pass live `Move` metadata to the
audit logger, and the v1.1 emission prefers live
data over the static fallback.

This is **NOT** RL training. **NOT** a 5k dataset.
**NOT** a benchmark. **NOT** a behavior / scoring /
default change.

## Real Decision → Audit Logger Path Confirmed

The audit logger is invoked at the **end** of
`DoublesDamageAwarePlayer.choose_move` in
`showdown_ai/bot_doubles_damage_aware.py:13377`.
The call site has access to:

- `battle` (poke-env `DoubleBattle`)
- `valid_orders` (`list[list[DoubleBattleOrder]]`,
  one list per slot)
- `scored_joint_orders`
  (`list[(joint_order, score, score_1, score_2)]`)
- `best_joint` (the selected joint order)
- `_v4a_legal_keys_slot0` / `_v4a_legal_keys_slot1`
  (set just before the call site at line 13329+)

The bot's `valid_orders[slot_idx]` is a list of
`DoubleBattleOrder` objects. Each order has an
`.order` attribute that is a poke-env `Move` object
with `id`, `base_power`, `category`, `type`, and
`deduced_target` fields. The audit logger does not
natively read these. RL-DATA-3a.2 wires a new helper
`_v1_1_live_move_metadata_for_audit` that walks
`valid_orders` and the active mon's `moves` dict
to build a per-move metadata map, then passes it
to `log_turn_decision` as `move_metadata_map_override`.

## Files Changed

- `doubles_engine/move_metadata.py` (modified, +120
  lines): added `collect_live_move_metadata` and
  `normalize_override` helpers, plus the new source
  labels `SOURCE_OVERRIDE`, `SOURCE_ORDER`,
  `SOURCE_LIVE`.
- `showdown_ai/doubles_decision_audit_logger.py`
  (modified, +60 lines): added
  `move_metadata_map_override` kwarg to
  `log_turn_decision`. The override is stashed on
  the turn_data as `_v11_move_metadata_override_raw`
  and consumed by `_populate_v1_1_move_metadata_map`.
- `showdown_ai/bot_doubles_damage_aware.py`
  (modified, +50 lines): added
  `_v1_1_live_move_metadata_for_audit` helper and
  passed `move_metadata_map_override=` to the audit
  logger call. The helper is wrapped in try/except
  so a failure cannot break the bot's choose_move
  path.
- `showdown_ai/doubles_audit_v1_1_smoke.py`
  (modified, +60 lines): updated the smoke to pass
  a `move_metadata_map_override` with
  `boltstrike` (a damaging move not in the static
  fallback) and the existing moves. Added a
  per-source count report to the smoke main.
- `tests/test_doubles_audit_v1_1_override.py` (new,
  22 tests):
  - `TestCollectLiveMoveMetadata` (8 tests):
    `collect_live_move_metadata` returns the right
    metadata for live `Order` objects, `Move`
    objects, `Pokemon.moves` dicts, and the static
    fallback. Order takes precedence over
    `pokemon`. Static fallback fills in missing
    entries. Unknown moves are tagged
    `metadata_source="unknown"`. Empty / no-args
    returns `{}`. V4a keys with malformed entries
    are skipped.
  - `TestNormalizeOverride` (7 tests):
    `normalize_override` normalizes a user-supplied
    override dict, handling case-variations
    (`Fake Out` → `fakeout`), tuple values
    (`(base_power, category)` convenience), missing
    fields, non-string keys (skipped), invalid
    inputs (returns `{}`), and custom
    `metadata_source` (preserved).
  - `TestAuditLoggerOverride` (3 tests): the audit
    logger accepts `move_metadata_map_override` as
    a kwarg. The override wins over the static
    fallback. Missing override entries fall back to
    the static table. A true unknown support move
    is still tagged `unknown_needs_probe` even with
    the override.
  - `TestOverrideEndToEnd` (4 tests): the smoke
    (clean fixture with override) is `READY`. A
    separate fixture with a true unknown support
    move (no override) is `WARN`, not `BLOCKED`.
    The bot's `_v1_1_live_move_metadata_for_audit`
    helper exists. The bot's helper returns a
    non-empty dict when given a real battle and
    live `valid_orders`.

## Override Plumbing Added

The audit logger's `log_turn_decision` signature
gained one new optional kwarg:

```python
log_turn_decision(
    ...,
    move_metadata_map_override: Optional[Dict[str, Dict]] = None,
    ...
)
```

The override is a dict mapping normalized move id
(lower-cased, no spaces / dashes / underscores /
apostrophes) to a metadata dict with at least
`base_power` and `category`. Optional fields:
`move_type`, `target`, `metadata_source`. The
override may have non-normalized keys (e.g.,
`"Fake Out"`, `"fake-out"`); the
`normalize_override` helper normalizes them.

The override is stashed on `turn_data` as
`_v11_move_metadata_override_raw` and consumed by
`_populate_v1_1_move_metadata_map` at the start of
the v1.1 emission.

The bot's `choose_move` call site calls
`_v1_1_live_move_metadata_for_audit(battle,
valid_orders)` to build the override and passes
the result to `log_turn_decision`. The helper is
wrapped in try/except so a failure returns `None`
and the audit logger falls back to the static
resolver (no behavior change in the error case).

## Metadata Source Precedence

The audit logger's `_populate_v1_1_move_metadata_map`
implements this precedence:

1. **Live override** (`metadata_source="override"`):
   if the caller passed `move_metadata_map_override`,
   the override is normalized and used first.
2. **Live order** (`metadata_source="order"`):
   `collect_live_move_metadata` walks
   `valid_orders` and resolves each move id from
   the `DoubleBattleOrder.order` poke-env `Move`
   object. This is the bot's primary path.
3. **Active mon's moves** (`metadata_source="pokemon"`):
   `collect_live_move_metadata` walks
   `battle.active_pokemon[i].moves` and resolves
   each move id from the poke-env `Move` object
   stored there.
4. **Static fallback** (`metadata_source="fallback"`):
   the static table in
   `doubles_engine.move_metadata._FALLBACK_MOVE_METADATA`.
5. **Unknown** (`metadata_source="unknown"`): the
   classifier treats this as "not damaging" (the
   conservative default). A truly unknown
   non-damaging support move surfaces here and is
   tagged `unknown_needs_probe` for the analyzer's
   Gate 17 soft warning.

The bot's `_v1_1_live_move_metadata_for_audit` helper
calls `collect_live_move_metadata` which already
walks orders first, then `pokemon.moves`, then the
static fallback. So the **bot's override is already
filled with live order / pokemon data** before
`_populate_v1_1_move_metadata_map` runs.

The override path adds **one more layer** above the
existing precedence: a caller can pass a pre-computed
override that wins over the static fallback. This is
the smoke / test path. In production, the bot's
helper produces a dict with `metadata_source="order"`
or `metadata_source="pokemon"`, which the audit
logger treats as the same as the override.

The audit JSONL records `metadata_source` per move
in the per-candidate classification, so downstream
tools (analyzer, inspector) can see whether the
metadata came from a live order, a real
`pokemon.moves` entry, the static fallback, or an
explicit override.

## Smoke Result

The smoke now includes a `move_metadata_map_override`
with five entries: `fakeout`, `hurricane`, `boltstrike`
(not in the static fallback), `raindance`, and
`protect`. The smoke also adds `boltstrike` to the
V4a legal-action keys for slot 0.

Smoke result:

```
======================================================================
RL-DATA-3a.2 — Tiny Local Audit Smoke (with override)
======================================================================

Stage 1: Audit emission
  battle records: 1
  audit turns: 1
  v1.1 keys present in turn: 8
  v1.1 keys missing in turn: 0

Stage 2: Builder
  rows: 1
  skipped: 0

Stage 3: Analyzer
  v1.1 readiness_impact: READY
  v1.1 n_rows: 1
  v1.0 n_rows: 0
  hard_blocks: 0
  warnings: 0

Per-candidate metadata source counts:
  fallback: 1   ← surf (not in override)
  override: 5   ← raindance, hurricane, boltstrike, fakeout, protect

Stage 4: Dry-run
  loaded rows: 1
```

Per-candidate classification:

```
raindance:  unknown=False metadata=override bp=0   cat=status   support=True
hurricane:  unknown=False metadata=override bp=110 cat=special  support=False
surf:       unknown=False metadata=fallback bp=90  cat=special  support=False
boltstrike: unknown=False metadata=override bp=130 cat=physical support=False
fakeout:    unknown=False metadata=override bp=40  cat=physical support=False
protect:    unknown=False metadata=override bp=0   cat=status   support=True
```

`boltstrike` is the smoking gun: it is a damaging
move NOT in the static fallback table. Without the
override, the classifier would have tagged it as
`unknown_needs_probe` (because `base_power=None`).
With the override, the classifier correctly
identifies it as damage-like
(`is_support_move=False`,
`unknown_support_move_detected=False`).

## Analyzer Result

The clean smoke fixture gives **READY** (0 warnings,
0 hard blocks). A separate fixture with a true
unknown non-damaging support move (e.g.,
`newgensupportmove`) gives **WARN** (Gate 17 soft
warning, no hard block). The detector is preserved.

## True Unknown Support Detector Status

**Preserved**. The detector fires for genuinely
unknown non-damaging support moves. The override
path is silent for known damaging moves; the
detector is not disabled globally. Tests in
`TestAuditLoggerOverride.test_override_with_unknown_move_still_flags`
and `TestOverrideEndToEnd.test_unknown_fixture_is_warn`
verify the detector still surfaces unknown moves.

## v1.0 Compatibility Status

42 v1.0 builder tests + 20 v1.0 analyzer tests +
42 v1.0 dry-run tests pass unchanged. The audit
logger continues to emit v1.0 fields exactly as
before. The new `move_metadata_map_override` and
`_v11_move_metadata_override_raw` fields are
additive. The v1.0 path is preserved.

## Dry-run Compatibility Status

42 v1.0 dry-run tests pass. The dry-run loads
JSONL via `_load_dataset(path)` which is
schema-agnostic. v1.1 rows are loaded as a strict
superset of v1.0. The new per-candidate
annotations (`metadata_source`,
`resolved_base_power`, `resolved_category`) are
additive; the dry-run ignores them.

## Fields Still Unavailable / Placeholders

- `terminal_win_loss` / `faint_caused` /
  `faint_suffered`: filled by the builder from
  episode metadata (audit logger doesn't have it).
- `turn_delta_hp`: not derivable from
  pre-decision snapshot.
- `config_hash` / `config_snapshot` / `format` /
  `team_id` / `opponent_team_id`: not available to
  the audit logger.
- `type_boost_applied`: would need execution-time
  data.
- `setter_move_raw_score`: emitted only if the
  audit logger has a recorded raw score for a
  setter move; otherwise `None`.
- The static fallback table still has 90 moves. A
  5k dataset will surface additional moves not in
  the fallback. The override path lets the bot
  resolve those at choose_move time, but the
  fallback table itself is not expanded in this
  phase.

## Why 5k Dataset Is Still Deferred Until a Small Real Local Battle Audit Smoke

A 5k audit would now rely on the live override path.
Before running 5k, we want a **small** real local
battle audit to verify:

1. The bot's `_v1_1_live_move_metadata_for_audit`
   helper runs without errors in the real
   `choose_move` path. The current helper is
   mocked in the smoke; a real audit would catch
   poke-env edge cases (e.g., missing order
   objects, mon faints, switch actions).
2. The audit JSONL records `metadata_source` values
   that are predominantly `order` or `pokemon` (not
   `fallback`). A high `fallback` rate would mean
   the live override path is not wired correctly.
3. The 18 v1.1 data-quality gates pass on a real
   audit (not just the smoke).
4. The action distribution covers all 9 support
   groups (Gate 12) and the support-move
   distribution is non-degenerate.

A future RL-DATA-3b phase would do this small real
audit (5-50 battles) before committing to a 5k
dataset. RL-DATA-3a.2 is a small cleanup phase after
RL-DATA-3a.1; it does not start RL-DATA-3b.

## Why RL Training Remains Not Approved

Per the RL-Readiness Checklist in
`logs/rl_data_1_turn_level_schema_plan.md`, all 13
items must be true before any training run. Current
status:

- [x] Schema plan (RL-DATA-1) — done.
- [x] Instrumentation (RL-DATA-2) — done.
- [x] Gate assertions (RL-DATA-2b) — done.
- [x] Audit logger emission (RL-DATA-3a) — done.
- [x] Move metadata enrichment (RL-DATA-3a.1) —
  done.
- [x] Live override wiring (RL-DATA-3a.2, this
  phase) — done. The audit JSONL can now carry
  live `Move` / order / `pokemon.moves` data via
  `move_metadata_map_override`.
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
- [x] No row has
  `blocked_action_resurrected_by_joint=True` — N/A
  (the audit logger hardcodes `False`).
- [ ] User has explicitly authorized Phase 7 — **not
  done**.
- [ ] AGENTS.md updated to mark Phase 7 as approved
  — **not done**.
- [ ] RL training readiness sign-off committed —
  not done.

**9 items remain incomplete.** Phase 7 (RL training)
is **not approved** per AGENTS.md and per the
13-item checklist.

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
- ✅ The override helper never infers from species
  or reads hidden state.
- ✅ The override helper never changes bot
  behavior — it only enriches the audit JSONL.
- ✅ The bot's helper is wrapped in try/except so
  a failure cannot break `choose_move`.
- ✅ The audit logger's v1.0 hot path is preserved
  (try/except wrap on the metadata helper).
- ✅ The true unknown-support detector is preserved.
- ✅ No `test_51` touch.
- ✅ No commit (per task).
- ✅ No push (per task).
- ✅ v1.0 backward compat preserved (220 existing
  tests pass).

## Tests Run and Results

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_audit_v1_1_override.py` (new) | 22 | **PASS** |
| `tests/test_doubles_audit_v1_1_move_metadata.py` | 27 | **PASS** |
| `tests/test_doubles_audit_v1_1_emission.py` | 24 | **PASS** |
| `tests/test_turn_level_v1_1_instrumentation.py` | 23 | **PASS** |
| `tests/test_v1_1_quality_gates.py` | 20 | **PASS** |
| `tests/test_build_turn_level_offline_dataset.py` | 42 | **PASS** |
| `tests/test_analyze_turn_level_offline_dataset_quality.py` | 20 | **PASS** |
| `tests/test_dryrun_turn_level_offline_policy.py` | 42 | **PASS** |
| **Total RL tests** | **220** | **PASS** |

Sanity tests (unchanged):

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_support_move_target_safety.py` | 91 | **PASS** |
| `tests/test_doubles_engine_support_targets.py` | 67 | **PASS** |
| `tests/test_doubles_ability_hard_safety.py` | 86 | **PASS** |
| **Total sanity tests** | **244** | **PASS** |
| **Grand total** | **464** | **PASS** |

## Files in This Phase

- `doubles_engine/move_metadata.py` (modified, +120
  lines: `collect_live_move_metadata` and
  `normalize_override` helpers, new source labels)
- `showdown_ai/doubles_decision_audit_logger.py`
  (modified, +60 lines: `move_metadata_map_override`
  kwarg, stash on turn_data, override-aware
  `_populate_v1_1_move_metadata_map`)
- `showdown_ai/bot_doubles_damage_aware.py`
  (modified, +50 lines:
  `_v1_1_live_move_metadata_for_audit` helper, wired
  into the `log_turn_decision` call)
- `showdown_ai/doubles_audit_v1_1_smoke.py`
  (modified, +60 lines: override in the smoke,
  `boltstrike` in legal keys, per-source count
  report)
- `tests/test_doubles_audit_v1_1_override.py` (new,
  22 tests)
- `logs/rl_data_3a_2_live_move_metadata_override.md`
  (this file)
- `logs/doubles_audit_v1_1_smoke.jsonl` (regenerated
  by the smoke with the override)
- `logs/doubles_audit_v1_1_smoke_dataset.jsonl`
  (regenerated by the smoke with the override)

## Recommended Next Phase

**RL-DATA-3b** — Small real local battle audit
smoke (5-50 battles, not 5k) + 18-gate evaluation.
This phase would:

1. Run a small real local battle audit (5-50
   battles) on `localhost:8000` with the
   `move_metadata_map_override` path enabled.
2. Verify the override helper runs without errors
   in the real `choose_move` path.
3. Verify the audit JSONL records predominantly
   `order` / `pokemon` metadata sources (not
   `fallback`).
4. Build a v1.1 dataset from the new audit.
5. Run all 18 v1.1 data-quality gates on the
   resulting dataset.
6. Compute 3 baseline comparisons (majority,
   current heuristic, simple score-based).
7. **No training.** RL training is still not
   approved per the 13-item checklist.

`Phase 7` (RL training) is **not approved** per
AGENTS.md and per the 13-item checklist.
