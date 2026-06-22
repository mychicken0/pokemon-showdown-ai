# RL-DATA-3a.1 — Audit Move Metadata Enrichment

**Date**: 2026-06-22
**Status**: `METADATA_ENRICHMENT_IMPLEMENTED_SMOKE_READY_NO_TRAINING`
**Phase**: RL-DATA-3a.1 (move metadata enrichment to fix false `unknown_needs_probe` tags)

## Goal

Fix the false-positive `unknown_needs_probe` tag for
known damaging moves (e.g., `fakeout`, `hurricane`)
in the v1.1 audit logger / builder path. RL-DATA-3a
emitted the v1.1 fields directly from the audit
logger, but the per-candidate support classifier had
no `base_power` / `category` to work with, so it
treated any move not in the SUPPORT-AUDIT-1 inventory
as `unknown_needs_probe`.

This is **NOT** RL training. **NOT** a 5k dataset.
**NOT** a benchmark. **NOT** a behavior / scoring /
default change.

## Root Cause Confirmed

The v1.1 audit logger emission calls
`classify_support_move_for_dataset(move_id,
base_power=None, category=None)`. The classifier
correctly identifies moves with `base_power > 0` or
`category in ("physical", "special")` as
**damage-like** (i.e., not a support move):

```python
# doubles_engine/support_targets.py:957-970
if (
    (base_power is not None and base_power > 0)
    or (category is not None and str(category).lower() in ("physical", "special"))
):
    return {
        "support_group": None,
        "is_support_move": False,
        "unknown_support_move_detected": False,
        ...
    }
```

But the audit logger does not record `base_power` or
`category` for V4a legal-action keys (the keys are
strings like `["move", "fakeout", 1, "no_mechanic"]`,
not poke-env `Move` objects). So the classifier fell
into the conservative path and tagged `fakeout`,
`hurricane`, and `surf` as `unknown_needs_probe` —
even though the SUPPORT-AUDIT-1 inventory does not
list them as support moves.

The result: the RL-DATA-3a smoke had a `WARN`
readiness_impact because of the Gate 17 soft warning
("1 v1.1 row(s) with
unknown_support_move_detected=True"). The row was
otherwise clean.

## Files Changed

- `doubles_engine/move_metadata.py` (new, 327 lines):
  the move metadata resolver module. Exposes
  `resolve_move_metadata_for_audit()`,
  `resolve_batch_for_audit()`, and the
  `_FALLBACK_MOVE_METADATA` static table. The
  resolver tries four sources, in order:
    1. The poke-env `Move` object reachable from
       `order.order` (if the caller passes an order).
    2. A direct poke-env `Move` object (if the caller
       passes one).
    3. The active mon's `pokemon.moves` dict (if the
       caller passes a poke-env `Pokemon`).
    4. A small static fallback table of 90 known
       moves.

- `doubles_engine/audit_v1_1_metadata.py` (modified):
  `_extract_v1_1_support_classification` now reads
  `turn.get("move_metadata_map")` and passes
  `base_power` / `category` into the classifier.
  Each per-candidate entry is annotated with
  `metadata_source`, `resolved_base_power`, and
  `resolved_category` so downstream tools can see
  where the metadata came from.

- `showdown_ai/doubles_decision_audit_logger.py`
  (modified): `_emit_v1_1_fields` now calls a new
  helper `_populate_v1_1_move_metadata_map` that
  builds the `move_metadata_map` from the V4a
  legal-action keys. The helper is wrapped in
  try/except so a failure in the metadata path
  never breaks the v1.1 emission (or the v1.0 hot
  path). The audit logger also supports a
  `move_metadata_map_override` kwarg on the turn
  data so future call sites (real production
  audits) can inject live metadata resolved at
  `choose_move` time.

- `showdown_ai/build_turn_level_offline_dataset.py`
  (modified): `_extract_v1_1_support_classification`
  reads the same `move_metadata_map` field and
  passes `base_power` / `category` into the
  classifier. This is the audit-fast path for the
  builder: when the audit logger has populated the
  map, the builder uses it; otherwise the builder
  falls back to the conservative
  `base_power=None, category=None` path.

- `tests/test_doubles_audit_v1_1_move_metadata.py`
  (new, 27 tests):
  - `TestMoveMetadataResolver` (9 tests): unit
    tests for `resolve_move_metadata_for_audit` —
    fallback for `fakeout` / `hurricane` / `surf` /
    `raindance` / `protect`, unknown moves,
    normalization, None / empty string.
  - `TestMoveMetadataResolverFromMoveObject` (2
    tests): resolver reads a poke-env `Move`
    object.
  - `TestMoveMetadataResolverFromPokemon` (1 test):
    resolver reads a poke-env `Pokemon.moves`
    dict.
  - `TestResolveBatch` (2 tests): batch resolver
    works on a list of move ids.
  - `TestClassifierWithMetadata` (6 tests):
    classifier with metadata correctly identifies
    `fakeout` / `hurricane` / `surf` as damage-like,
    `raindance` as support, and a true unknown
    non-damaging move as `unknown_needs_probe`.
  - `TestAuditMoveMetadataEndToEnd` (4 tests):
    audit logger emits `move_metadata_map` on the
    persisted turn, audit logger still surfaces
    true unknown moves, clean smoke is `READY`,
    unknown fixture is `WARN` (no hard block).
  - `TestFallbackTable` (3 tests): fallback table
    contains smoke + support-inventory moves and
    uses correct categories.

## Metadata Extraction Strategy

The resolver is **pure** and **observation-only**:

- No file I/O, no network, no species inference.
- It only reads the move id, the (optional) order
  object, the (optional) `Move` object, and the
  (optional) `Pokemon` object. No hidden state.
- It only matches on the move id, never on the
  species.

Resolution order:

1. **Order object**: if `order.order` looks like a
   poke-env `Move` (has `.id`, `.base_power`,
   `.category`, `.type`), use it directly.
   `metadata_source = "move"`.
2. **Direct Move object**: if `move` is passed and
   looks like a poke-env `Move`, use it.
   `metadata_source = "move"`.
3. **Pokemon moves dict**: if `pokemon` is passed
   and has a `moves` dict, look up the move id.
   `metadata_source = "pokemon"`.
4. **Static fallback table**: 90 known moves.
   `metadata_source = "fallback"`.
5. **Unknown**: missing source. `metadata_source =
   "unknown"`. The classifier treats this as
   "not damaging" (the conservative default).

In the audit logger, only step 4 (fallback) and
step 5 (unknown) are exercised in practice, because
the V4a legal-action keys are strings, not poke-env
objects. A future production audit can pass a
`move_metadata_map_override` kwarg on the turn
data to inject live metadata from poke-env
`Move` objects resolved at `choose_move` time.

## Exact Fallback List

The static fallback table has 90 moves. Format:
`(base_power, category)`. The full list is in
`doubles_engine/move_metadata.py` under
`_FALLBACK_MOVE_METADATA`. Highlights:

- **Smoke / test fixtures**: `fakeout` (40,
  physical), `hurricane` (110, special), `surf`
  (90, special).
- **Common support moves** (all 0 power, status):
  `raindance`, `sunnyday`, `sandstorm`, `hail`,
  `snowscape`, `electricterrain`, `grassyterrain`,
  `mistyterrain`, `psychicterrain`, `tailwind`,
  `trickroom`, `protect`, `detect`, `spikyshield`,
  `kingsshield`, `banefulbunker`, `silktrap`,
  `burningbulwark`, `obstruct`, `maxguard`,
  `healpulse`, `floralhealing`, `decorate`,
  `helpinghand`, `coaching`, `howl`, `lifedew`,
  `aromatherapy`, `healbell`, `followme`,
  `ragepowder`, `wideguard`, `quickguard`,
  `craftyshield`, `matblock`, `taunt`, `encore`,
  `disable`, `torment`, `thunderwave`, `willowisp`,
  `toxic`, `spore`, `sleeppowder`, `stunspore`,
  `charm`, `scaryface`, `screech`, `faketears`,
  `metalsound`, `gastroacid`, `icywind`,
  `electroweb`, `safeguard`, `lightscreen`,
  `reflect`, `auroraveil`, `magiccoat`, `haze`,
  `mist`, `courtchange`, `allyswitch`,
  `partingshot`, `memento`.
- **Common damaging moves** (non-zero power):
  `superpower` (120, physical), `closecombat` (120,
  physical), `voltswitch` (70, special), `uturn`
  (70, physical), `rapidspin` (50, physical),
  `thunderbolt` (90, special), `icebeam` (90,
  special), `flamethrower` (90, special),
  `psychic` (90, special), `earthquake` (100,
  physical), `rockslide` (75, physical),
  `stoneedge` (100, physical), `fireblast` (110,
  special), `hydropump` (110, special),
  `leafstorm` (130, special), `dracometeor` (130,
  special), `thunder` (110, special), `scald` (80,
  special), `matchagotcha` (90, special),
  `drainpunch` (75, physical), `gunkshot` (120,
  physical), `boltstrike` (130, physical),
  `waterfall` (80, physical).

The list is intentionally tiny. We do not build a
hand-written Pokédex. The fallback covers moves
that:

- appear in the SUPPORT-AUDIT-1 inventory,
- appear in the smoke / test fixtures, or
- appear in the bot's runtime move-id usage.

## Smoke Result Before / After

### Before (RL-DATA-3a)

```
Stage 3: Analyzer
  v1.1 readiness_impact: WARN
  v1.1 n_rows: 1
  v1.0 n_rows: 0
  hard_blocks: 0
  warnings: 1 item(s)  ← Gate 17: unknown_support_move_detected=True
```

Per-candidate classification in the dataset row:

```
raindance:  unknown=False support=True
hurricane:  unknown=True  support=True   ← false unknown
surf:       unknown=True  support=True   ← false unknown
fakeout:    unknown=True  support=True   ← false unknown
protect:    unknown=False support=True
```

### After (RL-DATA-3a.1)

```
Stage 3: Analyzer
  v1.1 readiness_impact: READY
  v1.1 n_rows: 1
  v1.0 n_rows: 0
  hard_blocks: 0
  warnings: 0 item(s)
```

Per-candidate classification in the dataset row:

```
raindance:  unknown=False support=True   bp=0   cat=status   src=fallback
hurricane:  unknown=False support=False  bp=110 cat=special  src=fallback
surf:       unknown=False support=False  bp=90  cat=special  src=fallback
fakeout:    unknown=False support=False  bp=40  cat=physical src=fallback
protect:    unknown=False support=True   bp=0   cat=status   src=fallback
```

`fakeout` / `hurricane` / `surf` are now correctly
identified as **damage-like** (`is_support_move =
False`), not `unknown_needs_probe`. The classifier
is fed `base_power` and `category` from the static
fallback table, and it correctly tags each move
based on its actual mechanics.

## Analyzer Result

The clean smoke fixture gives **READY** (no Gate 17
warning, no hard blocks). A separate fixture with a
true unknown non-damaging support move (e.g.,
`newgensupportmove`) gives **WARN** (Gate 17 soft
warning, no hard block). The detector is preserved.

## True Unknown Support Detector Status

The detector is **preserved**. Tests in
`TestClassifierWithMetadata`:

- `test_truly_unknown_non_damaging_is_unknown`:
  `classify_support_move_for_dataset("newgensupportmove",
  base_power=0, category="status")` returns
  `support_group = "unknown_needs_probe"`,
  `unknown_support_move_detected = True`.
- `test_audit_emits_unknown_support_move`:
  the real audit logger + the resolver emit
  `unknown_support_move_detected = True` for a
  fixture with a true unknown move.
- `test_unknown_fixture_is_warn`: a fixture with
  a true unknown support move produces a
  `WARN` analyzer result (Gate 17 fires, no hard
  block).

The detector is not disabled globally. It is only
quiet for known damaging moves that the resolver
identifies as damage-like.

## v1.0 Compatibility Status

42 v1.0 builder tests + 20 v1.0 analyzer tests +
42 v1.0 dry-run tests pass unchanged. The audit
logger continues to emit the v1.0 fields exactly
as before. The new `move_metadata_map` field is
additive (v1.1 only). The v1.0 path is preserved.

## Dry-run Compatibility Status

42 v1.0 dry-run tests pass. The dry-run loads
JSONL via `_load_dataset(path)` which is
schema-agnostic. v1.1 rows are loaded as a strict
superset of v1.0. The new per-candidate
annotations (`metadata_source`, `resolved_base_power`,
`resolved_category`) are additive; the dry-run
ignores them.

## Fields Still Unavailable / Placeholders

- `terminal_win_loss` / `faint_caused` /
  `faint_suffered`: filled by the builder from
  episode metadata (audit logger doesn't have it).
  Emitted as `None`.
- `turn_delta_hp`: not derivable from
  pre-decision snapshot. Emitted as `{}`.
- `config_hash` / `config_snapshot` / `format` /
  `team_id` / `opponent_team_id`: not available to
  the audit logger. Emitted as `None` / empty dict.
- `type_boost_applied`: would need execution-time
  data. Emitted as `[]`.
- `setter_move_raw_score`: emitted only if the
  audit logger has a recorded raw score for a
  setter move; otherwise `None`.
- **Live `Move` metadata**: the audit logger's
  `log_turn_decision` does not currently pass poke-env
  `Move` objects to the v1.1 emission. A future
  phase (RL-DATA-3b) can use the
  `move_metadata_map_override` kwarg to inject
  live metadata resolved at `choose_move` time. The
  static fallback covers the smoke / test /
  SUPPORT-AUDIT-1 inventory for now.

## Why 5k Dataset Remains Deferred Until This Is Clean

The 5k dataset would surface:

1. New damaging moves not in the static fallback
   table. The classifier would still tag them as
   `unknown_needs_probe` until a future phase
   expands the fallback. The current fallback is
   intentionally tiny (90 moves); a real 5k audit
   would need ~700+ Gen 9 moves for full coverage.
2. Poke-env `Move` object access patterns in the
   audit logger. RL-DATA-3a.1 prepares the path
   (`move_metadata_map_override` kwarg) but does
   not yet wire it. RL-DATA-3b would do that.
3. Pre-existing audit logger bugs (e.g., the
   `_enum_keys` character-list quirk).

RL-DATA-3a.1 is a small cleanup phase after
RL-DATA-3a. It does not start RL-DATA-3b.

## Why RL Training Remains Not Approved

Per the RL-Readiness Checklist in
`logs/rl_data_1_turn_level_schema_plan.md`, all 13
items must be true before any training run. Current
status:

- [x] Schema plan (RL-DATA-1) — done.
- [x] Instrumentation (RL-DATA-2) — done.
- [x] Gate assertions (RL-DATA-2b) — done.
- [x] Audit logger emission (RL-DATA-3a) — done.
- [x] Move metadata enrichment (RL-DATA-3a.1, this
  phase) — done. The audit JSONL now carries
  `move_metadata_map` and the per-candidate
  classification is correctly resolved for known
  damaging moves.
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
- ✅ The metadata resolver never infers from species
  or reads hidden state.
- ✅ The metadata resolver never changes bot
  behavior — it only enriches the audit JSONL.
- ✅ The audit logger's v1.0 hot path is preserved
  (try/except wrap on the metadata helper).
- ✅ The true unknown-support detector is preserved.
- ✅ No `test_51` touch.
- ✅ No commit (per task).
- ✅ No push (per task).
- ✅ v1.0 backward compat preserved (198 existing
  tests pass).

## Tests Run and Results

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_audit_v1_1_move_metadata.py` (new) | 27 | **PASS** |
| `tests/test_doubles_audit_v1_1_emission.py` | 24 | **PASS** |
| `tests/test_turn_level_v1_1_instrumentation.py` | 23 | **PASS** |
| `tests/test_v1_1_quality_gates.py` | 20 | **PASS** |
| `tests/test_build_turn_level_offline_dataset.py` | 42 | **PASS** |
| `tests/test_analyze_turn_level_offline_dataset_quality.py` | 20 | **PASS** |
| `tests/test_dryrun_turn_level_offline_policy.py` | 42 | **PASS** |
| **Total RL tests** | **198** | **PASS** |

Sanity tests (unchanged):

| test file | tests | result |
|-----------|------:|--------|
| `tests/test_doubles_support_move_target_safety.py` | 91 | **PASS** |
| `tests/test_doubles_engine_support_targets.py` | 67 | **PASS** |
| `tests/test_doubles_ability_hard_safety.py` | 86 | **PASS** |
| `tests/test_doubles_decision_timing_diagnostics.py` | 7 | **PASS** |
| `tests/test_doubles_voluntary_switch_extraction_fix.py` | 11 | **PASS** |
| **Total sanity tests** | **262** | **PASS** |
| **Grand total** | **460** | **PASS** |

## Files in This Phase

- `doubles_engine/move_metadata.py` (new, 327 lines)
- `doubles_engine/audit_v1_1_metadata.py` (modified,
  +50 lines: reads `move_metadata_map`, annotates
  per-candidate entries with `metadata_source` /
  `resolved_base_power` / `resolved_category`)
- `showdown_ai/doubles_decision_audit_logger.py`
  (modified, +85 lines: new `_populate_v1_1_move_metadata_map`
  helper, called from `_emit_v1_1_fields` before
  `populate_v1_1_audit_fields`)
- `showdown_ai/build_turn_level_offline_dataset.py`
  (modified, +35 lines: `_extract_v1_1_support_classification`
  reads `move_metadata_map` and passes
  `base_power` / `category` into the classifier)
- `tests/test_doubles_audit_v1_1_move_metadata.py`
  (new, 27 tests)
- `logs/rl_data_3a_1_move_metadata_enrichment.md`
  (this file)
- `logs/doubles_audit_v1_1_smoke.jsonl` (regenerated
  by the smoke)
- `logs/doubles_audit_v1_1_smoke_dataset.jsonl`
  (regenerated by the smoke)

## Recommended Next Phase

**RL-DATA-3b** — 5k+ battle audit + v1.1 audit
logger wiring + dataset build + 18-gate evaluation.
This phase would:

1. Wire the `move_metadata_map_override` kwarg in
   the audit logger so live poke-env `Move` objects
   resolved at `choose_move` time are passed into
   the v1.1 emission. This expands metadata
   coverage from "90 known moves" to "every move
   the bot has access to".
2. Run a 5k+ battle audit with the v1.1 audit
   logger enabled.
3. Build a v1.1 dataset from the new audit.
4. Run all 18 v1.1 data-quality gates on the
   resulting dataset.
5. Compute 3 baseline comparisons (majority,
   current heuristic, simple score-based).
6. **No training.** RL training is still not
   approved per the 13-item checklist.

`Phase 7` (RL training) is **not approved** per
AGENTS.md and per the 13-item checklist.
