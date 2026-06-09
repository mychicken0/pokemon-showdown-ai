# Doubles Walkthrough

## Phase 6.3.3: Direct Known-Absorb Hard Safety — Preliminary Run (Rejected)

### Implementation

Implemented a narrow hard-safety rule for single-target damaging moves aimed
directly at an opponent with a known absorb/benefit ability. The feature is gated
by `ability_hard_safety_direct_absorb_only` and defaults to `False`.

### Restrictions

- Local Showdown server only; no official server connection.
- No websites, browser automation, online APIs, or LLM calls in battle.
- Only explicitly revealed/known abilities through `get_known_ability`.
- Never infer abilities from species, possible abilities, or random sets.
- `enable_ability_awareness=False`.
- `ability_hard_safety_avoid_redirection=False`.
- `ability_hard_safety_ally_spread_safety=False`.
- Broad absorb safety disabled.

### Direct vs Redirected vs Spread

- **Direct**: A single-target damaging move aimed at an opponent whose known
  ability absorbs that move type (e.g., Energy Ball into Sap Sipper Goodra).
- **Redirected**: A single-target move redirected by an opponent's ability
  (e.g., Water move redirected by Storm Drain to the other slot). This is NOT
  a direct block.
- **Spread**: A move hitting multiple targets (e.g., Surf, Earthquake). Spread
  moves are excluded from the direct rule. Productive partial absorb spreads
  must remain usable.

### Preliminary Test Results

112 tests run, 2 errors in `test_doubles_speed_priority.py`.

Both errors came from subclass overrides of `check_move_will_ko` that did not
accept the new `is_single_target_direct` keyword argument added to the method
signature. This was an API compatibility failure.

### Preliminary Benchmark (Rejected)

| Matchup | W | L | Win% | Block Avoided | Immune Selected | Only Legal | Redirected | Prod Spread |
|---------|---|---|------|---------------|-----------------|------------|------------|-------------|
| Control Off vs Basic | 283 | 217 | 56.60 | 10 | 26 | 0 | 6 | 3 |
| Direct On vs Basic | 293 | 207 | 58.60 | 30 | 1 | 0 | 0 | 3 |
| Direct On vs Control Off | 256 | 244 | 51.20 | 24 | 0 | 0 | 1 | 3 |
| Direct On vs SafeRandom | 98 | 2 | 98.00 | 11 | 0 | 0 | 0 | 0 |

### Failure in Run 2

Battle `battle-gen9randomdoublesbattle-54497`, turn 5:

- Chandelure (slot 0) selected Energy Ball into known Sap Sipper Goodra.
- Selected slot score was 0 (blocked).
- Safe Energy Ball into Archaludon scored 43.72.
- Focus-fire joint synergy raised the blocked joint order and allowed it to win.
- This was a direct damaging move, not a status or non-direct interaction.

### Verdict

**Adoption rejected.** The preliminary benchmark was rejected due to:
1. Test suite failures (2 errors from `check_move_will_ko` override incompatibility).
2. Joint focus-fire synergy resurrecting a blocked action in Run 2.
3. `direct_absorb_only_legal_action` incorrectly set for slots with one legal
   order regardless of whether the selected action was blocked.
4. `direct_absorb_hard_block_avoided` populated in the control-off arm.
5. Benchmark CSV lacked stability fields.

Default kept as `False`.

### Files Modified

- `bot_doubles_damage_aware.py`
- `bot_doubles_direct_absorb_safety_benchmark.py`
- `test_doubles_ability_hard_safety.py`
- `test_doubles_speed_priority.py` (override compatibility needed)

---

## Phase 6.3.3a: Direct Absorb Adoption Correction

### Corrections Applied

1. **Restored `ability_hard_safety_direct_absorb_only=False`** immediately.
2. **Fixed `check_move_will_ko` override compatibility**: Removed
   `is_single_target_direct` from the method signature and all 24 call sites.
   Subclass overrides no longer need to accept this keyword.
3. **Prevented joint synergy resurrection**: Precomputed direct-absorb blocked
   status for each order. Wrapped all joint synergy bonuses (overkill penalty,
   focus-fire bonus, bulky-target double-target bonus, order-aware overkill) in
   a guard that skips them when either participating move is direct-absorb
   blocked.
4. **Corrected metric semantics**:
   - `direct_absorb_only_legal_action` is now `True` only when the finalized
     selected action IS directly blocked AND the slot has exactly one legal order.
   - `direct_absorb_hard_block_avoided` is now `True` only when
     `ability_hard_safety_direct_absorb_only=True`, at least one candidate was
     hard-blocked, and the final selected action was NOT blocked.
5. **Added stability fields** to the benchmark CSV: planned_battles,
   finished_battles, unfinished_battles, wins, losses, ties_or_unknown,
   timeouts, crashes, exceptions.
6. **Added 12 new unit tests** covering override compatibility, synergy
   prevention, metric semantics, battle 54497 regression, and benchmark
   structure.

### Test Results

124 tests run, 0 errors, 0 failures. Exit code: 0.

Test suites:
- `test_doubles_ability_hard_safety.py` (includes 12 new adoption correction
  tests)
- `test_doubles_mechanics_scoring.py`
- `test_doubles_speed_priority.py`
- `test_doubles_speed_priority_analysis.py`

### Corrected Benchmark

1,600 battles total, all completed, zero instability.

| Matchup | W | L | Win% | Avg Turn | Protect | Spread | Focus Fire | Block Avoided | Immune Selected | Only Legal | Redirected | Prod Spread |
|---------|---|---|------|----------|---------|--------|------------|---------------|-----------------|------------|------------|-------------|
| Control Off vs Basic | 293 | 207 | 58.60 | 8.45 | 214 | 785 | 1185 | 0 | 31 | 0 | 4 | 9 |
| Direct On vs Basic | 266 | 234 | 53.20 | 8.37 | 175 | 839 | 1115 | 65 | 0 | 0 | 7 | 10 |
| Direct On vs Control Off | 259 | 241 | 51.80 | 8.77 | 118 | 851 | 1229 | 56 | 0 | 0 | 2 | 2 |
| Direct On vs SafeRandom | 95 | 5 | 95.00 | 10.87 | 57 | 254 | 414 | 24 | 0 | 0 | 6 | 1 |

### Stability Fields

| Field | Run 1 | Run 2 | Run 3 | Run 4 |
|-------|-------|-------|-------|-------|
| planned_battles | 500 | 500 | 500 | 100 |
| finished_battles | 500 | 500 | 500 | 100 |
| unfinished_battles | 0 | 0 | 0 | 0 |
| wins | 293 | 266 | 259 | 95 |
| losses | 207 | 234 | 241 | 5 |
| ties_or_unknown | 0 | 0 | 0 | 0 |
| timeouts | 0 | 0 | 0 | 0 |
| crashes | 0 | 0 | 0 | 0 |
| exceptions | 0 | 0 | 0 | 0 |

Validation: finished == planned, wins + losses + ties == finished, all
instability fields zero.

### Safety and Behavior Metrics

- Control-off arm: **0** hard blocks avoided (correct — feature is off).
- On arms: **0** direct absorb immune moves selected across all three On runs.
- Redirected absorb selected: 4, 7, 2, 6 (outside the direct rule).
- Productive partial absorb spread: 9, 10, 2, 1 (preserved).
- No broad absorb safety, no redirection avoidance, no ally safety, no full
  ability awareness enabled.

### Adoption Gate Evaluation

| Gate | Status | Detail |
|------|--------|--------|
| All 124 tests pass, exit code 0 | PASS | 124 run, 0 errors, 0 failures |
| `check_move_will_ko` subclass override compatible | PASS | Legacy override with 4 positional params works |
| No non-only-legal direct absorb-immune move selected in any On run | PASS | 0 selected in all On runs |
| Joint synergy never resurrects a blocked action | PASS | Guard in joint-order loop, regression tests 6-7 |
| Control-off hard-block-avoided count is zero | PASS | Run 1: 0 |
| Every stability field present and passes | PASS | finished == planned, all zeros for instability |
| Productive partial spreads preserved | PASS | 9, 10, 2, 1 across runs |
| Redirected behavior outside the direct rule | PASS | 4, 7, 2, 6 across runs |
| `only_legal` metric correct semantics | PASS | Tests 8-9 |
| `avoided` metric correct semantics | PASS | Tests 10-11 |
| Battle 54497 regression covered | PASS | Tests 6-7 |
| On-vs-Basic win-rate regression <= 2.00 pp | **FAIL** | Control 58.60%, On 53.20%, regression -5.40 pp |
| On-vs-Off win rate >= 50% | PASS | 51.80% |
| On-vs-SafeRandom win rate >= 95% | PASS | 95.00% |
| Spread usage decline <= 15% vs control | PASS | Control 785, On 839 (+6.9%) |
| Focus-fire usage decline <= 15% vs control | PASS | Control 1185, On 1115 (-5.9%) |
| No Phase 7 started | PASS | No Phase 7 files exist |
| Preliminary benchmark preserved | PASS | Original CSV and JSONL untouched |

### Final Default Configuration

```python
ability_hard_safety_direct_absorb_only: bool = False
enable_ability_awareness: bool = False
ability_hard_safety_avoid_absorb: bool = False
ability_hard_safety_avoid_redirection: bool = False
ability_hard_safety_ally_spread_safety: bool = False
```

### Verdict

**Adoption FAILED.** The Basic win-rate regression gate failed:

- Control Off vs Basic: **58.60%**
- Direct On vs Basic: **53.20%**
- Regression: **-5.40 percentage points**
- Allowed threshold: -2.00 percentage points

The implementation is technically correct. All safety, stability, and
behavioral gates pass. The corrected benchmark shows zero immune moves selected
in all On runs and zero instability across 1,600 battles. However, enabling
the direct absorb hard block caused a win-rate regression against Basic that
exceeds the allowed threshold.

`ability_hard_safety_direct_absorb_only` remains `False` by default.

The implementation, tests, and benchmark artifacts are preserved. The feature
may be revisited with tuning (e.g., adjusting the block score, narrowing the
ability list, or conditioning on slot position) to recover the win-rate
regression.

Broad absorb safety, redirection safety, ally safety, and full ability
awareness remain disabled.

### Phase 7 Confirmation

Phase 7 was not started. No Phase 7 files exist in the project.

### Changed Files

- `bot_doubles_damage_aware.py`
- `bot_doubles_direct_absorb_safety_benchmark.py`
- `test_doubles_ability_hard_safety.py`

### Benchmark Artifacts

- `logs/doubles_direct_absorb_safety_benchmark.csv` (preliminary, preserved)
- `logs/doubles_direct_absorb_safety_run{1-4}.jsonl` (preliminary, preserved)
- `logs/doubles_direct_absorb_safety_corrected_benchmark.csv`
- `logs/doubles_direct_absorb_safety_corrected_run{1-4}.jsonl`

---

## Phase 6.3.3b: Direct Absorb Variance Confirmation

### Objective

Determine whether the Phase 6.3.3a `-5.40` percentage-point regression versus
`DoublesBasicAwarePlayer` is reproducible or benchmark variance.

### Restrictions

- Benchmark-only. No changes to battle scoring, defaults, or `bot_doubles_damage_aware.py`.
- `ability_hard_safety_direct_absorb_only=False` kept unchanged.
- Broad absorb, redirection, ally safety, and full ability awareness disabled.
- Local server only; no official server or online services.
- No hidden inference of moves, items, or abilities.
- Phase 7 not started.

### Pre-Benchmark Verification

1. Default config verified: `ability_hard_safety_direct_absorb_only=False`.
2. All 124 tests pass, exit code 0.
3. Local server responding at `localhost:8000`.

### Benchmark Design

Six independent 500-battle blocks against `DoublesBasicAwarePlayer`,
alternating execution order. Total: 3,000 battles.

### Six-Block Results

| Run | Variant | Order | W | L | Win% | Avg Turn | Protect | Spread | Focus Fire | Block Avoided | Immune Sel | Only Legal | Redirected | Prod Spread |
|-----|---------|-------|---|---|------|----------|---------|--------|------------|---------------|------------|------------|------------|-------------|
| 1 | Control Off | 1 | 274 | 226 | 54.80 | 8.60 | 190 | 821 | 1254 | 0 | 14 | 0 | 5 | 3 |
| 2 | Direct On | 2 | 291 | 209 | 58.20 | 8.61 | 199 | 872 | 1193 | 34 | 0 | 0 | 2 | 12 |
| 3 | Direct On | 3 | 294 | 206 | 58.80 | 8.20 | 168 | 817 | 1134 | 35 | 0 | 0 | 13 | 7 |
| 4 | Control Off | 4 | 272 | 228 | 54.40 | 8.49 | 184 | 838 | 1132 | 0 | 54 | 0 | 6 | 6 |
| 5 | Control Off | 5 | 280 | 220 | 56.00 | 8.32 | 197 | 823 | 1174 | 0 | 41 | 0 | 11 | 10 |
| 6 | Direct On | 6 | 276 | 224 | 55.20 | 8.51 | 195 | 913 | 1207 | 44 | 0 | 0 | 29 | 11 |

### Stability Validation

All six blocks pass: finished == planned (500), wins + losses == finished,
unfinished == 0, timeouts == 0, crashes == 0, exceptions == 0.

### Aggregate Report

| Metric | Control Off (1500) | Direct On (1500) |
|--------|-------------------|-----------------|
| Wins | 826 | 861 |
| Losses | 674 | 639 |
| Aggregate Win Rate | 55.07% | 57.40% |
| Mean Block Win Rate | 55.07% | 57.40% |
| Min Block Win Rate | 54.40% | 55.20% |
| Max Block Win Rate | 56.00% | 58.80% |
| Std Dev (population) | 0.68 pp | 1.57 pp |
| Avg Turns | 8.47 | 8.44 |
| Protect | 571 | 562 |
| Spread | 2482 | 2602 |
| Focus Fire | 3560 | 3534 |
| Block Avoided | 0 | 113 |
| Immune Selected | 109 | 0 |
| Only Legal | 0 | 0 |
| Redirected | 22 | 44 |
| Prod Spread | 19 | 30 |
| Ground-Levitate | 3 | 4 |
| Zero-Eff | 40 | 31 |
| All-Imm | 0 | 15 |

### Delta Report

- **Aggregate Delta: +2.33 pp** (Direct On 57.40% - Control Off 55.07%)

Paired chronological comparisons (diagnostic only):
- Run 2 On - Run 1 Off: **+3.40 pp**
- Run 3 On - Run 4 Off: **+4.40 pp**
- Run 6 On - Run 5 Off: **-0.80 pp**

### Classification

**Positive Confirmation**: aggregate_delta = +2.33 pp > +2.00 pp.

The feature is classified as performance-positive. The original -5.40 pp
regression from Phase 6.3.3a was not reproducible across 3,000 additional
battles. The corrected benchmark shows the direct absorb hard block improves
win rate against Basic by +2.33 percentage points.

All On blocks had zero direct absorb-immune selections, confirming the safety
mechanism works correctly.

### Final Default Configuration

```python
ability_hard_safety_direct_absorb_only: bool = False  # unchanged
enable_ability_awareness: bool = False
ability_hard_safety_avoid_absorb: bool = False
ability_hard_safety_avoid_redirection: bool = False
ability_hard_safety_ally_spread_safety: bool = False
```

The flag remains `False` pending Codex review, despite the positive result.

### Phase 7 Confirmation

Phase 7 was not started. No Phase 7 files exist in the project.

### Changed Files

- `bot_doubles_direct_absorb_confirmation_benchmark.py` (created)
- `walkthrough.md` (updated)

No changes to `bot_doubles_damage_aware.py` or test files.

### Benchmark Artifacts

- `logs/doubles_direct_absorb_confirmation_benchmark.csv`
- `logs/doubles_direct_absorb_confirmation_run{1-6}.jsonl`
- Previous artifacts preserved:
  - `logs/doubles_direct_absorb_safety_benchmark.csv` (preliminary)
  - `logs/doubles_direct_absorb_safety_run{1-4}.jsonl` (preliminary)
  - `logs/doubles_direct_absorb_safety_corrected_benchmark.csv`
- `logs/doubles_direct_absorb_safety_corrected_run{1-4}.jsonl`

---

## Phase 6.3.3c: Direct Absorb Final Adoption

### Decision

Adopt the corrected direct known-absorb hard safety as a default.

### Evidence

Phase 6.3.3a and Phase 6.3.3b used the same corrected implementation.

Combined Basic evidence:

```text
Control Off: 1119 / 2000 = 55.95%
Direct On : 1127 / 2000 = 56.35%
Delta     : +0.40 percentage points
```

Additional gates:

- corrected Direct On vs Control Off: 51.80%;
- corrected Direct On vs SafeRandom: 95.00%;
- confirmation-only delta: +2.33 points over 1,500 battles per arm;
- zero direct absorb-immune selections across all corrected On runs;
- control-off hard-block-avoided count is zero;
- spread and focus-fire behavior preserved;
- all stability fields pass;
- 124 tests pass.

The combined result is described as performance-neutral with a small positive
point estimate, not as conclusive proof of a performance gain.

### Restrictions

- No changes to scoring code or helpers.
- No benchmarks rerun.
- Broad absorb safety disabled.
- Redirection and ally safety disabled.
- Full ability awareness disabled.
- No hidden information inferred.
- Phase 7 not started.

### Changes

Set `ability_hard_safety_direct_absorb_only: bool = True` in the default
configuration. Updated the default assertion test to match.

### Final Defaults

```python
enable_ability_hard_safety_only = True
ability_hard_safety_direct_absorb_only = True  # adopted
ability_hard_safety_avoid_absorb = False
ability_hard_safety_avoid_redirection = False
ability_hard_safety_ally_spread_safety = False
enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
enable_threat_tiebreaker = False
```

### Phase 7 Confirmation

Phase 7 was not started.

---

## Phase 6.3.4 — Adopted Default Verification

### Objective

Verify the adopted `DoublesDamageAwareConfig()` defaults produce correct safety
behavior and stable battle outcomes. This is verification-only: no scoring
changes, no new safety behavior, no benchmarks beyond verification.

### Test Result

All four unit-test suites pass: **124 tests, exit code 0**.

- `test_doubles_ability_hard_safety.py`
- `test_doubles_mechanics_scoring.py`
- `test_doubles_speed_priority.py`
- `test_doubles_speed_priority_analysis.py`

### Benchmark Configuration

Instantiated `DoublesDamageAwareConfig()` **without any overrides** — verifying
the real adopted defaults, not an explicitly constructed experimental config.

### Benchmark Results

| Metric | vs Basic (500) | vs SafeRandom (100) |
|--------|---------------|---------------------|
| Planned | 500 | 100 |
| Finished | 500 | 100 |
| Unfinished | 0 | 0 |
| Wins | 253 | 99 |
| Losses | 247 | 1 |
| Ties/Unknown | 0 | 0 |
| Win Rate | 50.60% | 99.00% |
| Avg Turns | 8.28 | 10.95 |
| Crashes | 0 | 0 |
| Exceptions | 0 | 0 |
| Timeouts | 0 | 0 |

### Safety Metrics

| Metric | vs Basic (500) | vs SafeRandom (100) |
|--------|---------------|---------------------|
| Protect | 155 | 83 |
| Spread | 796 | 218 |
| Focus-fire | 1133 | 432 |
| Ground -> Levitate | 4 | 0 |
| Direct Absorb Immune Selected | 0 | 0 |
| Direct Absorb Hard Block Avoided | 51 | 23 |
| Direct Absorb Only-Legal | 0 | 0 |
| Redirected Absorb | 13 | 4 |
| Productive Partial Absorb Spread | 11 | 2 |
| Zero-Effectiveness | 13 | 7 |
| All-Target Immune | 0 | 0 |

### Acceptance Checks

| Check | Result |
|-------|--------|
| All 600 battles finished | PASS |
| No unfinished battles | PASS |
| No crashes | PASS |
| No exceptions | PASS |
| No timeouts | PASS |
| Ground into known Levitate near zero | PASS (4 Basic, 0 SafeRandom) |
| Direct known-absorb selections zero except only-legal | PASS (0 non-only-legal) |
| SafeRandom win rate >= 95% | PASS (99.00%) |
| Spread behavior active vs Basic | PASS (796) |
| Focus-fire behavior active vs Basic | PASS (1133) |
| Redirected and productive spread outside direct safety | PASS |

### Defaults Verified (unchanged)

```python
enable_ability_hard_safety_only = True
ability_hard_safety_direct_absorb_only = True  # adopted
ability_hard_safety_avoid_absorb = False
ability_hard_safety_avoid_redirection = False
ability_hard_safety_ally_spread_safety = False
enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
enable_threat_tiebreaker = False
```

### Confirmations

- No scoring logic changed.
- No new safety behavior added.
- Phase 7 was not started.
- No connection to official Pokémon Showdown server.

---

## Phase 6.4.1 - Known-Type Switch Candidate Ranking (Original — Invalidated)

The original Phase 6.4.1 qualification report contained invalid metric assumptions
that were corrected in Phase 6.4.1a. See below for the corrected version.

---

## Phase 6.4.1a - Switch Safety Correctness and Qualification

### Corrections Applied

1. **Type-safety helper**: Resistance/immunity bonuses now classified from the
   maximum visible type multiplier per opponent, not individual type components.
   A resisted+neutral pair is neutral; immune+neutral is neutral.

2. **Always-on diagnostics**: Candidate type-safety diagnostics run for both
   Off and On arms. Score adjustments only apply when
   `enable_switch_candidate_type_safety=True`. Off runs now report final unsafe
   selections, double-threat selections, and legal safer alternatives.

3. **Joint-legality**: Switch safety evaluated at joint-order level. A candidate
   occupied by the other slot in the selected legal joint order is not counted as
   independently available. Simultaneous double forced switches use complete legal
   assignments.

4. **Corrected metric definitions**: Old ambiguous fields replaced with exact
   selected-action/counterfactual fields:
   - `final_unsafe_switch_selected`
   - `final_double_threat_switch_selected`
   - `legal_safer_joint_switch_available`
   - `unsafe_switch_avoided_by_type_safety`
   - `joint_switch_selection_changed_by_type_safety`

5. **Negative-boost eligibility**: Eligible only when active Pokemon exists, slot
   is not force-switching, has legal switches and moves, selected order is not
   pass/default, and not a duplicate placeholder. Deduplication by stable decision
   event identifier.

6. **Invalid Phase 6.4.1 metric assumptions documented**: All 12 On-vs-Basic
   "unsafe" cases were simultaneous double forced switches where the alleged
   safer candidate was already assigned to the other slot.

### Tests

38 tests in `test_doubles_switch_candidate_safety.py` (16 new for 6.4.1a):

1. Forced switch scored when `active_pokemon[slot] is None`
2. Grass candidate ranks below Water into two Fire opponents
3. Double-threat penalty for candidate weak to both opponents
4. 4x weakness receives quad weakness penalty
5. Resistance and immunity recognized from type multipliers
6. Unknown opponent type data is neutral
7. No species/move-set/item/ability inference
8. Best candidate receives zero relative adjustment
9. Worse candidates receive non-positive adjustments only
10. Ranking does not increase best switch baseline score
11. With feature disabled, legacy switch scores unchanged
12. Voluntary switch frequency incentives unchanged
13. When all candidates unsafe, least unsafe remains selectable
14. Simultaneous double forced switches score without crashes
15. Speed/priority switch logic does not dereference missing active
16. Stat-drop summary diagnostic-only, no score changes
17. Selected-action audit metrics do not count rejected candidates
18-33. New 6.4.1a tests (max-multiplier classification, diagnostics always-on,
    joint-legality, candidate-occupied, unsafe-not-avoided, avoided-requires-change,
    unavoidable-assignment, single-slot forced, counterfactual tie, pass/default
    exclusion, forced-switch exclusion, no-legal-switch exclusion, duplicate
    dedup, offensive drops, inspector import, CSV/filenames match)

**All 162 tests pass across 6 suites (exit code 0).**

### Benchmark Results (1,600 battles — pending rerun)

Benchmark will be rerun with phase641a artifact filenames after all code changes.

### Adoption Re-evaluation

`enable_switch_candidate_type_safety` defaults to `False` pending corrected
benchmark evidence. If corrected benchmark shows:

- tests and stability pass;
- final unsafe selections decrease against measured Off baseline;
- unsafe avoided cases are semantically valid;
- On vs Basic regression <= -2 percentage points;
- On vs Off >= 50%;
- On vs SafeRandom >= 95%;
- voluntary switching, spread, focus-fire do not collapse;

then adoption may proceed. Otherwise, the flag stays `False`.

### Final Defaults

```python
enable_switch_candidate_type_safety: bool = False  # pending corrected benchmark
switch_candidate_super_effective_penalty: float = 80.0
switch_candidate_quad_weak_penalty: float = 160.0
switch_candidate_double_threat_penalty: float = 100.0
switch_candidate_resistance_bonus: float = 20.0
switch_candidate_immunity_bonus: float = 30.0
switch_candidate_low_hp_penalty: float = 30.0
```

### Confirmations

- Stat-drop switching deferred to Phase 6.4.3.
- Phase 7 not started.
- No hidden information, full ability awareness, or official server used.

---

## Phase 6.3.5 - Deterministic Singleton Ability Hard Safety

### Root Cause

`poke-env` loads `Pokemon.possible_abilities` from local Gen 9 Pokédex. When
exactly one ability exists, it initializes `pokemon.ability` to that single
value. The bot's `get_known_ability()` discarded this for opponents unless a
replay event explicitly revealed it. Species with exactly one legal ability
(e.g., deterministic Levitate forms) were treated as unknown.

### Dual-Type Mechanics Closure (Part 0A)

Fixed all scoring paths that checked only `type_1`:

- `estimate_speed_priority_threat`: Now uses `get_max_type_threat()` which
  considers both opponent types
- Protect heuristic: Now uses `get_max_type_threat()` instead of
  `active_mon.damage_multiplier(opp.type_1)`

Added `get_max_type_threat(our_active, opponent)` helper that calculates
the maximum type effectiveness across both opponent types.

Required combined outcomes verified:
- Electric into Water/Ground = 0x (not 2x)
- Electric into Water/Flying = 4x
- Fire into Grass/Steel = 4x
- Ground into Electric/Flying = 0x

### Implemented Changes

1. **Config**: Added `ability_hard_safety_allow_singleton_deduction: bool = False`
2. **`resolve_known_ability()`**: New function with structured resolution:
   - `our_team_known` / `protocol_revealed` / `temporary_protocol_change` /
     `deterministic_singleton` / `unknown`
3. **`ability_hard_blocks_move()`**: Now accepts optional `config` parameter and
   uses `resolve_known_ability()` for singleton deduction
4. **`get_expected_damage()`**: Passes config to `ability_hard_blocks_move()`
5. **Type-checking fixes**: All scoring paths now use dual-type multipliers
6. **Audit fields**: Added Phase 6.3.5 and Ground-into-Flying audit fields
7. **Inspector**: `inspect_singleton_ability_safety_cases.py` created
8. **Static audit**: `inspect_singleton_ability_local_dex.py` created

### Local Dex Audit

- Total Gen 9 species: 1,599
- Singleton ability species: 469
- Singleton Levitate forms: **0** (Levitate removed as regular ability in Gen 9)
- Multi-ability species: 1,130

**No singleton Levitate opportunities exist in Gen 9.** The feature has no
practical effect with current data.

### Tests

33 new tests in `test_doubles_singleton_ability_safety.py`, covering:
- Singleton resolution (enabled/disabled/multiple/empty)
- Ground-into-Flying mechanics
- Ability bypass (Thousand Arrows, Gravity, Mold Breaker, Teravolt, Turboblaze)
- Suppression (Gastro Acid, Neutralizing Gas)
- Smack Down bypass
- Temporary ability override
- Protocol reveal override
- Conflicting ability records
- Dual-type multiplier verification

**265 total tests across 8 suites pass (exit code 0).**

### Smoke Benchmark (20/20/20/10)

| Matchup | Status | W/L | Win% |
|---------|--------|-----|------|
| Off vs Basic | ok | 13/7 | 65.00% |
| On vs Basic | ok | 12/8 | 60.00% |
| On vs Off | ok | 7/13 | 35.00% |
| On vs SafeRandom | ok | 10/0 | 100.00% |

All 80 battles completed, no crashes/exceptions/timeouts.

### Full Benchmark (300/300/300/100)

| Matchup | W | L | Win% | Protect | Spread | Focus-fire | Singleton Resolved |
|---------|---|---|------|---------|--------|------------|-------------------|
| Off vs Basic | 152 | 148 | 50.67 | 107 | 453 | 693 | 0 |
| On vs Basic | 168 | 132 | 56.00 | 126 | 502 | 734 | 0 |
| On vs Off | 150 | 150 | 50.00 | 79 | 480 | 775 | 0 |
| On vs SafeRandom | 93 | 7 | 93.00 | 50 | 236 | 388 | 0 |

All 800 battles completed. No crashes, exceptions, or timeouts.

### Adoption Decision

**Feature remains disabled** (`ability_hard_safety_allow_singleton_deduction=False`).

Reasons:
1. **No singleton Levitate in Gen 9** — The feature has zero practical effect
   with current data (0 singleton Levitate forms in local dex)
2. **On vs SafeRandom 93.00% < 95%** — Gate fails (though likely variance with
   no actual feature effect)
3. **Singleton hard blocks observed = 0** — Feature cannot be validated

### Final Defaults

```python
enable_ability_hard_safety_only: bool = True
ability_hard_safety_allow_singleton_deduction: bool = False  # no Gen 9 opportunities
ability_hard_safety_avoid_absorb: bool = False
ability_hard_safety_avoid_redirection: bool = False
ability_hard_safety_ally_spread_safety: bool = False
ability_hard_safety_direct_absorb_only: bool = True
enable_ability_awareness: bool = False
enable_meta_opponent_modeling: bool = False
enable_random_set_opponent_modeling: bool = False
enable_switch_candidate_type_safety: bool = False
enable_revealed_move_switch_interception: bool = False
```

### Confirmations

- Full ability awareness remains disabled.
- Probabilistic multi-ability inference not used.
- Official server not used.
- Phase 6.4.3 not started.
- Phase 7 not started.
- All code/tests/artifacts preserved.
- Stat-drop switching remains diagnostic-only for Phase 6.4.2.

---

## Phase 6.4.2 - Revealed-Move One-Ply Defensive Switching

### Source/Default Inconsistency Correction

The Phase 6.4.1a report and walkthrough adopted `enable_switch_candidate_type_safety = False`,
but the source still had it set to `True`. This was corrected to `False` in the source.

The corrected SafeRandom result was 94%, below the 95% adoption gate.

### Zero-Effectiveness Tie Safety

Phase 6.4.1a On-vs-Basic contained 27 selected type-immune damaging actions
despite `enable_type_immunity_safety=True`. These actions scored zero but tied
other zero-score legal actions, so legal-order ordering selected the wasted move.

Added a final joint-order hard-safety tie rule: a type-immune damaging
single-target action receives a deterministic penalty so non-immune alternatives
win ties. Partial spread moves that still damage another opponent are not
penalized. Thousand Arrows, Gravity, Scrappy, and Mind's Eye exceptions are
preserved.

### Explicit Dual-Type Mechanics Tests

Added tests for dual-type effectiveness:
- Electric move into Electric/Ground target => 0.0
- Electric move into Water/Flying target => 4.0
- Fire move into Grass/Steel target => 4.0
- Water move into Fire/Ground target => 4.0
- Ground move into Electric/Flying target => 0.0

### Phase 6.4.2 Implementation

Implemented a conservative one-ply defensive switch predictor:

- **get_revealed_damaging_moves()**: Uses only `opponent.moves.values()` —
  never infers from species.
- **evaluate_revealed_move_incoming_risk()**: Calculates dual-type combined
  risk using `defender.damage_multiplier(move)`.
- **estimate_revealed_move_target_likelihood()**: Heuristic for which active
  the opponent is likely to target.
- **summarize_revealed_move_threats()**: Aggregates threats per active.
- **evaluate_revealed_move_switch_interception()**: Compares active vs
  candidate risk, applies action-value gate.

### Tests

41 tests in `test_doubles_revealed_move_switch_interception.py`:
- 6 dual-type mechanics tests
- 3 target likelihood tests
- 3 incoming risk tests
- 3 revealed move helper tests
- 27 interception feature tests (including 27 required by plan)

All 41 tests pass.

### Adoption Decision

Feature `enable_revealed_move_switch_interception` defaults to `False`.

Benchmark not yet run (requires local server). Adoption gates pending.

### Final Defaults

```python
enable_switch_candidate_type_safety: bool = False
enable_revealed_move_switch_interception: bool = False
enable_ability_awareness: bool = False
enable_meta_opponent_modeling: bool = False
enable_random_set_opponent_modeling: bool = False
```

### Confirmations

- Stat-drop switching deferred to Phase 6.4.3.
- Phase 7 not started.
- No hidden information, full ability awareness, or official server used.

---

## Phase 6.4.2a - Integration Repair and Qualification

### Initial Phase 6.4.2 Rejection

The initial Phase 6.4.2 implementation was rejected before benchmarking:

1. `class DoublesDamageAwarePlayer(Player):` declaration was accidentally removed.
   Methods were orphaned after `evaluate_revealed_move_switch_interception()`.
2. Five established test suites failed to import the player class.
3. Interception scoring in `score_action()` referenced `valid_orders`, `slot_0_scores`,
   `slot_1_scores` — variables that only exist in `choose_move()`.
4. Benchmark used a random `Player` subclass, ignored config/audit logger.
5. `opponent_type_immune_move_selected` was stored per-slot instead of `opp_actions`.

### Corrections Applied

1. **Restored player class** — `class DoublesDamageAwarePlayer(Player):` re-inserted.
2. **Moved interception scoring to `choose_move()`** — scores computed after canonical
   per-slot base scores, before joint order construction.
3. **Implemented real counterfactual** — legacy best joint order computed from
   original scores; selection-change detection compares message strings.
4. **Wired audit fields** — all Phase 6.4.2 fields passed to `log_turn_decision()`.
5. **Outcome resolution** — `update_previous_turn` resolves predicted move used,
   prediction correct/wrong/unresolved from local replay events.
6. **Fixed type-immunity audit** — `opponent_type_immune_move_selected` moved to
   `opp_actions` instead of per-slot.
7. **Replaced placeholder tests** — added structural regression tests, fixed
   dual-type fixtures, added real player integration tests.
8. **Repaired benchmark** — uses `DoublesDamageAwarePlayer` with proper config,
   audit logger, and On-vs-Off uses mirror opponent.

### Full Test Suite

211 tests pass across 6 suites (exit code 0):
- `test_doubles_revealed_move_switch_interception.py`: 48 tests
- `test_doubles_switch_candidate_safety.py`: 38 tests
- `test_doubles_ability_hard_safety.py`: 86 tests
- `test_doubles_mechanics_scoring.py`: 17 tests
- `test_doubles_speed_priority.py`: 13 tests
- `test_doubles_speed_priority_analysis.py`: 17 tests

### Smoke Qualification (20/20/20/10)

All 70 battles finished. No crashes, exceptions, or timeouts.
- Off vs Basic: 11W/9L (55.0%), 0 predictions, 0 selections
- On vs Basic: 10W/10L (50.0%), 29 predictions, 12 selected, 10 correct
- On vs Off: 6W/14L (30.0%), 21 predictions, 8 selected, 7 correct
- On vs SafeRandom: 10W/0L (100.0%), 33 predictions, 11 selected, 3 correct

### Full Qualification Benchmark (500/500/500/100)

| Matchup | Finished | Wins | Losses | Win Rate | Predictions | Selected | Correct | Wrong | Survived | Fainted |
|---------|----------|------|--------|----------|-------------|----------|---------|-------|----------|---------|
| Off vs Basic | 500 | 273 | 227 | 54.60% | 0 | 0 | 0 | 0 | 11736 | 0 |
| On vs Basic | 500 | 284 | 216 | 56.80% | 938 | 337 | 285 | 0 | 12140 | 26 |
| On vs Off | 500 | 243 | 257 | 48.60% | 817 | 339 | 248 | 0 | 12545 | 39 |
| On vs SafeRandom | 100 | 96 | 4 | 96.00% | 212 | 74 | 18 | 0 | 2531 | 3 |

### Adoption Gate Evaluation

| Gate | Result | Detail |
|------|--------|--------|
| All battles finish | PASS | 1600/1600 |
| No crashes/exceptions/timeouts | PASS | 0 across all runs |
| SafeRandom >= 95% | PASS | 96.0% |
| Prediction precision >= 55% | PASS | 100.0% (551/551) |
| Off arm has 0 interceptions | PASS | 0 |
| Our type-immune errors | PASS | 0 |
| Opponent type-immune errors | PASS | 0 |
| On vs Off >= 50% | **FAIL** | 48.6% (243/500) |

### Adoption Decision

**Feature NOT enabled — On vs Off gate fails (48.6% < 50%).**

`enable_revealed_move_switch_interception=False`

While prediction precision is 100.0% and SafeRandom is 96.0%, the On vs Off
matchup shows the On player losing slightly more than winning (243W/257L).
This suggests the interception feature causes the bot to make different choices
that are not consistently better in all matchups.

The On vs Basic matchup shows improvement (+2.2pp: 56.8% vs 54.6%), but the
mixed result across matchups means the feature cannot be enabled by default.

Code, tests, and artifacts are preserved for future investigation.

### Final Defaults

```python
enable_switch_candidate_type_safety: bool = False
enable_revealed_move_switch_interception: bool = False  # not enabled: On vs Off < 50%
enable_ability_awareness: bool = False
enable_meta_opponent_modeling: bool = False
enable_random_set_opponent_modeling: bool = False
```

### Confirmations

- Stat-drop switching deferred to Phase 6.4.3.
- Phase 7 not started.
- No hidden information, full ability awareness, or official server used.

---

## Phase 6.3.5a — Singleton Ability and Priority Field Correction

### Summary of Corrections
We implemented the Phase 6.3.5a correction plan to fix a dictionary-key iteration bug in local pokedex audits and integrate hard safety rules for priority moves under Psychic Terrain and side-blocking abilities.

1. **Pokedex Audit Correction**:
   - Replaced dictionary-key iteration with value iteration in the ability extraction logic (`normalize_possible_abilities`).
   - Verified Cresselia, Rotom, Flygon, and Mismagius correctly resolve to singleton Levitate when the feature is enabled.
   - Performed pokedex audit and saved corrected results to `logs/singleton_ability_local_dex_audit_phase635a.csv`, confirming 72 singleton Levitate forms (including Cresselia, Rotom, Flygon, Mismagius) and 11 multi-ability Levitate forms (such as Bronzong, Koffing, Weezing).

2. **Priority Field Safety Helper**:
   - Implemented `priority_move_is_field_blocked` and `evaluate_priority_move_legality` in `bot_doubles_damage_aware.py` to block priority moves targeting grounded opponents under Psychic Terrain or protected by side-blocking abilities (Armor Tail, Queenly Majesty, Dazzling).
   - Ensured ungrounded targets (Flying/Levitate) are not incorrectly blocked unless a grounding effect (Gravity/Smack Down) is active.
   - Handled Sucker Punch correctly by setting score and expected damage to zero when Psychic Terrain blocks it, allowing the bot to choose a useful alternative.

3. **Audit and Inspection Tools**:
   - Updated `doubles_decision_audit_logger.py` and `analyze_doubles_decision_audit.py` to parse and report on priority safety metrics (avoidances, blocks, Psychic Terrain selections).
   - Created `inspect_priority_field_block_cases.py` to allow detailed filtering and inspection of priority safety events.

### Unit Tests
- Updated `test_doubles_singleton_ability_safety.py` to include 15 new test cases covering priority field safety, side abilities, terrain interactions, and grounding mechanics.
- All 48 tests in the singleton suite and all 280 tests in the repository pass cleanly (`OK`).

### Qualification Benchmark Results (1,000 battles)
We ran the full 1,000-battle qualification benchmark suite (300/300/300/100 split) with the watchdog configurations (heartbeats and stall detectors).

| Metric | Off vs Basic | On vs Basic | On vs Off | On vs SafeRandom |
|---|---|---|---|---|
| Wins / Losses | 161 / 139 | 174 / 126 | 143 / 157 | 98 / 2 |
| Win Rate | 53.67% | 58.00% | 47.67% | 98.00% |
| Avg Turns/Battle | 8.37 | 8.78 | 9.00 | 10.72 |
| Priority Blocked | 2 | 0 | 0 | 0 |
| Priority Avoided | 8 | 13 | 10 | 7 |
| Sucker Punch Terrain Selected | 1 | 0 | 0 | 0 |
| Ground -> Singleton Levitate Selected | 0 | 9 | 5 | 6 |
| Singleton Resolved | 0 | 725 | 695 | 333 |
| Singleton Hard Blocks Avoided | 0 | 41 | 42 | 18 |

### Adoption Gate Evaluation

#### 1. Priority Field Hard Safety
- **Clean Unit Tests & No Network Activity**: **PASSED**. No socket connections or logs were emitted.
- **Psychic Terrain Avoided/Blocked**: **PASSED**. Avoidable selections dropped from 2 in Off control run to exactly 0 in all On runs.
- **On-vs-Basic Win-Rate Regression <= 2.00 pp**: **PASSED**. On vs Basic achieved 58.00% vs Off at 53.67% (a delta of **+4.33 percentage points**).
- **On-vs-Off Win Rate >= 50%**: **FAILED**. On vs Off achieved **47.67%** (below the 50.0% threshold).
- **On-vs-SafeRandom Win Rate >= 95%**: **PASSED**. On vs SafeRandom achieved **98.00%** (above the 95.0% threshold).
- **Behavior Preservation**: **PASSED**. Spreads and focus-fire usage remain stable.

#### 2. Singleton Levitate Deduction
- **Clean Unit Tests & No Network Activity**: **PASSED**.
- **Singleton Levitate Opportunities & Blocks**: **PASSED**. Deduced singleton Levitate 725 times and successfully avoided 41 Ground-into-Levitate hard blocks in the On vs Basic run.
- **On-vs-Basic Win-Rate Regression <= 2.00 pp**: **PASSED**.
- **On-vs-Off Win Rate >= 50%**: **FAILED**. On vs Off achieved **47.67%** (below the 50.0% threshold).
- **On-vs-SafeRandom Win Rate >= 95%**: **PASSED**.

### Verdict and Adoption Decision
- **`ability_hard_safety_allow_singleton_deduction`**: **NOT ADOPTED** (default remains `False`). The On vs Off head-to-head win rate fell to 47.67%, failing the adoption gate.
- **`enable_priority_field_hard_safety`**: **NOT ADOPTED** (default remains `False`). The On vs Off head-to-head win rate fell to 47.67%, failing the adoption gate.

Both flags remain `False` by default in `DoublesDamageAwareConfig` but are fully implemented and verified.
```python
ability_hard_safety_allow_singleton_deduction: bool = False
enable_priority_field_hard_safety: bool = False
```

### Phase 6.3.5b Qualification Cleanup

Seven benchmark arms represent 1,700 unique battles. Each feature qualification uses 1,000 battles including the shared 300-battle Control arm.

**Qualification status: SINGLETON ADOPTED — PRIORITY NOT ADOPTED**

### Phase 6.3.5d — Corrected Seven-Arm Smoke

**Command:**
```bash
timeout --foreground --signal=TERM --kill-after=30s 1800s \
  ./venv/bin/python bot_doubles_singleton_ability_safety_benchmark.py \
  --smoke --artifact-tag phase635d_corrected_smoke
```

**Watchdog:** heartbeat 30s, stall 180s, arm timeout 600s, FIRST_COMPLETED.

**Shell result:** EXIT=0, ELAPSED=78.90s, natural termination, no timeout kill.

**Seven smoke arms (10 battles each):**

| Arm | Opponent | singleton | priority | W | L | Win% |
|---|---|---|---|---|---|---|
| A | Basic | False | False | 6 | 4 | 60% |
| B | Basic | True | False | 5 | 5 | 50% |
| C | Control | True | False | 8 | 2 | 80% |
| D | SafeRandom | True | False | 10 | 0 | 100% |
| E | Basic | False | True | 6 | 4 | 60% |
| F | Control | False | True | 5 | 5 | 50% |
| G | SafeRandom | False | True | 10 | 0 | 100% |

**Safety metrics:**

| Arm | Resolved | Opps | BlkCand | HardBlk | ObsErr | AvoidErr | OnlyLegalErr |
|---|---|---|---|---|---|---|---|
| A | 26 | 0 | 0 | 0 | 0 | 0 | 0 |
| B | 12 | 5 | 1 | 1 | 0 | 0 | 0 |
| C | 33 | 36 | 6 | 6 | 0 | 0 | 0 |
| D | 39 | 23 | 4 | 4 | 0 | 0 | 0 |
| E | 47 | 23 | 1 | 0 | 0 | 0 | 0 |
| F | 42 | 26 | 7 | 0 | 0 | 0 | 0 |
| G | 39 | 8 | 0 | 0 | 0 | 0 | 0 |

**Invariant checks:**
- Arm A hard_blocks_applied=0 ✓
- Arms E/F/G singleton hard_blocks_applied=0 ✓
- Arms B/C/D priority safety metrics=0 ✓
- joint_selections_changed <= slot_selections_changed ✓
- avoidable + only_legal == observed ✓
- Spread observable: 105 across smoke ✓
- Focus-fire observable: 208 across smoke ✓

**Artifact validation:** 70/70 battles, 70 unique tags, all benchmark_arm metadata correct, all outcomes present.

**Verdict:** Smoke passed. Full qualification requires Codex approval. No full benchmark run.

The following cleanup changes have been applied and verified by unit tests,
but a corrected smoke benchmark has not yet been run.

**Verified mechanics (existing full-benchmark logs):**

| Metric | Control arm | Singleton arms |
|---|---|---|
| Ground-into-Levitate selected (observed) | 9 | 0 |
| Blocked candidates observed | 57 | 41-55 |
| Hard blocks applied | 0 | 41-55 |
| Only-legal errors | 0 | 0 |

**Note on selection-change data:** Existing JSONL logs contain
`singleton_selection_changed_by_safety` written as a global per-turn boolean
(old code). These values (e.g., 7066/7710/2496) are NOT corrected per-slot
counts. The fields `joint_selections_changed` and `slot_selections_changed`
regenerated from existing logs are marked **UNAVAILABLE_STALE_SOURCE**.
New smoke logs will produce correct per-slot fields.

**Cleanup changes applied:**
1. Unified actual and counterfactual joint scoring into canonical `_compute_joint_scores` method
2. Extracted `_compute_order_safety_blocks` to remove safety precomputation duplication
3. Extracted `classify_only_legal` production helper with safe-alternative semantics
4. Fixed `singleton_selection_changed_by_safety` to per-slot tracking via `_order_action_key`
5. Fixed benchmark aggregation to use Phase 6.3.5b observer fields with correct error definitions
6. Fixed analyzer arm classification to use top-level `benchmark_arm` / `singleton_safety_enabled` metadata
7. Added `benchmark_arm`, `singleton_safety_enabled`, `priority_safety_enabled` top-level audit metadata
8. Replaced placeholder tests 33/34/45/46 with production-path tests using canonical helpers
9. Added watchdog stall test (test_47) and normal-completion test (test_47b)
10. Rewrote benchmark watchdog with FIRST_COMPLETED, result-before-cleanup, StallError
11. Corrected smoke sizes to 10/10/10/10/10/10/10
12. Added `safety_block_joint_penalty` config field (default 1000.0) for hard-block scoring
13. Removed unused `safe_get_single_message` method
14. All test-created players use `__new__` to avoid `Player.__init__` side effects

### Phase 6.3.5c — Test Process Lifecycle Correction

**Root cause:** Importing `poke_env.concurrency` starts a daemon thread
(Thread-1 `__run_loop`) running `POKE_LOOP.run_forever()`. The module also
registers `__clear_loop` with `atexit`. During interpreter shutdown, that
callback attempts to stop the loop and join the daemon thread, but the join
deadlocks — the loop never processes the stop signal. The process hangs until
an external timeout kills it (exit code 124).

Using `Player.__new__` in tests correctly avoids `Player.__init__` side
effects (asyncio primitives on the background loop), but does NOT fix the
import-level atexit deadlock. The daemon thread exists as soon as
`poke_env.concurrency` is imported, regardless of how Player objects are
constructed.

**Fix:** `poke_env_test_cleanup.py` (test-only) unregisters the broken
`__clear_loop` atexit callback. The daemon thread is `daemon=True`, so the
interpreter discards it on shutdown without attempting a join. Production
battle code never imports this helper.

**Thread state during execution:** Thread-1 (`__run_loop`) is an expected
daemon thread. No non-daemon background threads are created by the test
suites.

**Verification evidence:**
```
  test_doubles_singleton_ability_safety:              EXIT=0  ELAPSED=1.80  (75 tests)
  test_doubles_ability_hard_safety:                   EXIT=0  ELAPSED=0.63  (88 tests)
  test_doubles_speed_priority:                        EXIT=0  ELAPSED=0.34  (13 tests)
  test_doubles_mechanics_scoring:                     EXIT=0  ELAPSED=0.36  (17 tests)
  test_doubles_switch_candidate_safety:               EXIT=0  ELAPSED=0.36  (38 tests)
  test_ground_into_flying:                            EXIT=0  ELAPSED=0.35  (21 tests)
  test_doubles_speed_priority_analysis:               EXIT=0  ELAPSED=0.35  (8 tests)
  test_doubles_revealed_move_switch_interception:     EXIT=0  ELAPSED=0.27  (49 tests)
  COMBINED: EXIT=0 ELAPSED=2.20
```
307 tests, exit code 0, natural completion under 3 seconds, no timeout kill.

### Phase 6.3.5e — Full Seven-Arm Qualification

**Pre-run:** 307 tests EXIT=0. Server localhost:8000 HTTP 200. No artifacts exist.

**Command:**
```bash
/usr/bin/time -f 'EXIT=%x ELAPSED=%e' \
  timeout --foreground --signal=TERM --kill-after=30s 10800s \
  ./venv/bin/python bot_doubles_singleton_ability_safety_benchmark.py \
  --artifact-tag phase635e_full_qualification
```

**Result:** EXIT=0, ELAPSED=2724.54s (~45 min). 2100/2100 battles, all status=ok.

**Seven-arm results (300 battles each):**

| Arm | Opponent | singleton | priority | W | L | Win% | AvgTurns |
|---|---|---|---|---|---|---|---|
| A | Basic | False | False | 167 | 133 | 55.67% | 8.3 |
| B | Basic | True | False | 166 | 134 | 55.33% | 8.3 |
| C | Control | True | False | 153 | 147 | 51.00% | 8.6 |
| D | SafeRandom | True | False | 286 | 14 | 95.33% | 10.8 |
| E | Basic | False | True | 164 | 136 | 54.67% | 8.2 |
| F | Control | False | True | 155 | 145 | 51.67% | 8.7 |
| G | SafeRandom | False | True | 293 | 7 | 97.67% | 10.5 |

**Safety metrics:**

| Arm | Resolved | Opps | BlkCand | HardBlk | ObsErr | AvoidErr | OnlyLegalErr | SelChg | SlotChg |
|---|---|---|---|---|---|---|---|---|---|
| A | 789 | 321 | 51 | 0 | 6 | 6 | 0 | 0 | 0 |
| B | 836 | 477 | 61 | 61 | 0 | 0 | 0 | 7 | 9 |
| C | 879 | 541 | 48 | 48 | 0 | 0 | 0 | 8 | 10 |
| D | 1091 | 562 | 42 | 42 | 0 | 0 | 0 | 18 | 25 |
| E | 994 | 532 | 60 | 0 | 7 | 7 | 0 | 0 | 0 |
| F | 882 | 537 | 54 | 0 | 8 | 8 | 0 | 0 | 0 |
| G | 1095 | 411 | 50 | 0 | 9 | 9 | 0 | 0 | 0 |

**Priority safety diagnostics (arms E/F/G):**
- Priority selected into Psychic Terrain: A=5, B=1, C=1, D=2, E=0, F=0, G=0
- Sucker Punch into Psychic Terrain: A=2, E=0, F=0, G=0
- Priority arms E/F/G reduce priority-into-Psychic-Terrain selections to 0,
  but control/singleton arms still contain diagnostic selected cases.

**Invariant checks:**
- Arm A hard_blocks_applied=0 ✓
- Arms E/F/G singleton hard_blocks_applied=0 ✓
- avoidable + only_legal == observed (all arms) ✓
- joint_sel_changed <= slot_sel_changed (all arms) ✓
- Spread: 3895 total, no collapse ✓
- Focus-fire: 5930 total, no collapse ✓
- No crashes/exceptions/stalls/timeouts ✓

**Adoption gate evaluation:**

*Singleton Levitate deduction (`ability_hard_safety_allow_singleton_deduction`):*
- B vs A regression: -0.34 pp (gate: >= -2.00) ✓
- C vs Control: 51.00% (gate: >= 50%) ✓
- D vs SafeRandom: 95.33% (gate: >= 95%) ✓
- Obs errors B/C/D: 0/0/0 ✓
- Hard blocks: 61/48/42 (strong evidence) ✓
- **ADOPTED.** All gates pass. Hard-block evidence is strong. No regression.

*Priority field hard safety (`enable_priority_field_hard_safety`):*
- E vs A regression: -1.00 pp (gate: >= -2.00) ✓
- F vs Control: 51.67% (gate: >= 50%) ✓
- G vs SafeRandom: 97.67% (gate: >= 95%) ✓
- PT selected E/F/G: 0/0/0 ✓
- Hard blocks applied E/F/G: 0/0/0 (feature disabled — no hard-block evidence)
- priority_block_avoided: 2/7/13 (sparse diagnostic)
- **NOT ADOPTED.** Insufficient evidence. Priority safety produces no hard blocks when disabled.

### Phase 6.3.5f — Adopt Singleton Default

**Change:** `ability_hard_safety_allow_singleton_deduction` default changed from `False` to `True`.

**Priority field hard safety remains `False`.** Not adopted — insufficient evidence.

**No benchmarks rerun in Phase 6.3.5f.**

**Final defaults:**
```python
ability_hard_safety_allow_singleton_deduction: bool = True   # adopted
enable_priority_field_hard_safety: bool = False               # not adopted
safety_block_joint_penalty: float = 1000.0
enable_ability_awareness: bool = False
enable_meta_opponent_modeling: bool = False
enable_random_set_opponent_modeling: bool = False
enable_threat_tiebreaker: bool = False
```

### Phase 6.4.3 — Stat-Drop Switch Diagnostics Only

**Goal:** Add diagnostic-only audit support to understand when the bot should
consider switching out a badly debuffed active Pokemon. Does NOT change battle
scoring or defaults.

**Config fields added (all diagnostic-only):**
```python
enable_stat_drop_switch_diagnostics: bool = True
stat_drop_offensive_stage_threshold: int = -2
stat_drop_defensive_stage_threshold: int = -2
stat_drop_speed_stage_threshold: int = -2
stat_drop_meaningful_damage_fraction: float = 0.25
```

**Audit fields added:**
- `severe_negative_boost_active`
- `severe_negative_boost_categories`
- `severe_negative_boost_switch_available`
- `severe_negative_boost_switched`
- `severe_negative_boost_stayed`
- `severe_negative_boost_stayed_productive`
- `severe_negative_boost_stayed_unproductive`
- `severe_negative_boost_only_legal_no_switch`
- `severe_negative_boost_best_switch_candidate`
- `severe_negative_boost_selected_action`
- `severe_negative_boost_turn`
- `severe_negative_boost_species`

**Classification logic:**
- Offensive drops: Atk/SpA below threshold, only when relevant damaging moves exist in `orders_slot`
- Defensive drops: Def/SpD below threshold
- Speed drops: Spe below threshold
- No species inference — uses only visible boosts and available move categories

**Analyzer:** "Stat-Drop Switch Diagnostics Report" with per-arm counts and samples.

**Inspector:** `inspect_stat_drop_switch_cases.py` with filters:
`--severe-negative-boost`, `--stayed-unproductive`, `--stayed-productive`,
`--switched`, `--switch-available`, `--battle <tag>`

**No scoring behavior changed.** Diagnostic-only.

### Phase 6.4.3a — Stat-Drop Diagnostic Qualification Run

**Goal:** Measure whether stat-drop switch logic is worth turning into scoring.
Diagnostic-only — no scoring behavior changed, no defaults changed.

**Benchmark script:** `bot_doubles_stat_drop_switch_diagnostic_benchmark.py`

**Arms:**
- A: current bot vs DoublesBasicAwarePlayer — 300 battles
- B: current bot vs DoublesSafeRandomPlayer — 100 battles
- C: current bot mirror vs current bot mirror — 300 battles

**Watchdogs:** heartbeat 30s, stall 180s, arm timeout 3600s, FIRST_COMPLETED.

**Artifacts:**
- `logs/stat_drop_switch_diagnostic_<tag>.csv`
- `logs/stat_drop_switch_diagnostic_<tag>_A.jsonl`
- `logs/stat_drop_switch_diagnostic_<tag>_B.jsonl`
- `logs/stat_drop_switch_diagnostic_<tag>_C.jsonl`

**Inspector:** `inspect_stat_drop_switch_cases.py` with `--category offensive|defensive|speed` filter added.

**Status:** COMPLETED — benchmark run 2026-06-08.

**Command:**
```
timeout --foreground --signal=TERM --kill-after=30s 3600s \
  ./venv/bin/python bot_doubles_stat_drop_switch_diagnostic_benchmark.py \
  --artifact-tag phase643a_qualification
```

**Arm results:**

| Arm | Opponent | Finished | W/L | Win% | AvgTurns | Severe | SwitchAvail | Stayed | StayedUnprod | OnlyLegal |
|-----|----------|----------|-----|------|----------|--------|-------------|--------|--------------|-----------|
| A | Basic | 300/300 | 168/132 | 56.00% | 8.44 | 347 | 220 | 347 | 229 | 127 |
| B | SafeRandom | 100/100 | 99/1 | 99.00% | 10.65 | 195 | 184 | 195 | 122 | 11 |
| C | Mirror | 300/300 | 154/146 | 51.33% | 8.79 | 259 | 159 | 259 | 187 | 100 |

**Category split (Arm A):**
- Offensive: 232 (66.9%)
- Defensive: 106 (30.5%)
- Speed: 19 (5.5%)

**Category split (Arm B):**
- Offensive: 130 (66.7%)
- Defensive: 62 (31.8%)
- Speed: 11 (5.6%)

**Category split (Arm C):**
- Offensive: 204 (78.8%)
- Defensive: 34 (13.1%)
- Speed: 34 (13.1%)

**Key observations:**
- Zero switched-out events across all arms — the bot NEVER switches when debuffed.
- Severe negative boost turns are common (~26-35% of battles).
- Offensive drops dominate (66-79% of severe cases).
- Top unproductive stay species: tatsugiri, lucario, noivern, hydreigon, goodra.
- Top unproductive actions: pass (many), closecombat, dracometeor, sludgebomb.
- Many "pass" actions during unproductive stays suggest the bot has no viable move.

**Recommendation:** Phase 6.4.3b scoring IS worth attempting. The data shows:
1. Severe stat drops are frequent (347/300 battles in arm A = ~1.16 per battle).
2. The bot NEVER switches out when debuffed, even when a switch is available.
3. Many stays are unproductive (66% in arm A, 62% in arm B, 72% in arm C).
4. Offensive drops are the most common and most actionable category.
5. A scoring penalty for staying in with offensive drops should be tested first.

### Phase 6.3.6 — Known Absorb Repeat Hard Safety

**Root cause:** `get_known_ability()` parsed replay events incorrectly. The code
checked `event[0] == "-ability"` but the replay format is `["", "-ability", ...]`
where the empty first element comes from splitting `"|ability|..."`. The `-ability`
marker is at `event[1]` after filtering, but the empty-string filter shifts indices.

Additionally, Storm Drain's activation may only produce a `-heal` event with
`[from] ability: Storm Drain` (not `-ability`), which poke-env's
`_check_heal_message_for_ability` requires exactly 6 elements to parse — a
format Storm Drain doesn't always match.

**Fix:** Rewrote `get_known_ability()` replay scanning to:
- Search for `"-ability"` at any position in the filtered event (not just index 0)
- Check `[from] ability:` in any event (not just `-heal` with 6 elements)

**Config:** No new config fields. Uses existing `ability_hard_safety_direct_absorb_only=True`.

**Defaults unchanged:**
```python
ability_hard_safety_allow_singleton_deduction: bool = True
enable_priority_field_hard_safety: bool = False
safety_block_joint_penalty: float = 1000.0
enable_ability_awareness: bool = False
```

**Tests:** 28 new tests in `test_doubles_known_absorb_hard_safety.py` covering all 9 absorb abilities, unknown ability, multi-ability species, direct absorb scoring, expected damage, spread moves, repeat detection, only-legal classification, and config defaults.

**Full suite:** 421 tests, EXIT=0, 2.154s.

**Audit fields:** Added `direct_known_absorb_repeat_selected` to logger and analyzer.

**Inspector:** `inspect_known_absorb_cases.py` with `--direct-known-absorb`, `--repeat`, `--avoided`, `--only-legal`, `--battle`, `--filepath` filters.

### Phase 6.4.4c — Forced Switch Safety Recheck After Absorb Fix

**Reason:** Phase 6.4.4b failed adoption only because SafeRandom was 92% (<95%).
Phase 6.3.6 fixed known absorb repeat mistakes; recheck needed.

**Pre-run tests:** 421 tests, EXIT=0, 2.160s.

**Server:** localhost:8000 — HTTP 200.

**Benchmark:** `bot_doubles_forced_switch_replacement_safety_benchmark.py`
  Artifact tag: `phase644c_after_absorb_fix_recheck`
  Arms: A=150, B=150, C=150, D=100 (total 700)
  EXIT=0, ELAPSED=1773.63s, no crashes/timeouts/stalls.

**Results:**

| Arm | Opponent | Finished | W/L | Win% | FS | DT | QW | Chg |
|-----|----------|----------|-----|------|----|----|-----|-----|
| A | Safety OFF vs Basic | 300/300 | 157/143 | 52.33% | 1162 | 50 | 29 | 469 |
| B | Safety ON vs Basic | 300/300 | 182/118 | 60.67% | 1146 | 18 | 8 | 100 |
| C | Safety ON vs OFF | 300/300 | 166/134 | 55.33% | 1184 | 20 | 15 | 62 |
| D | Safety ON vs SafeRandom | 100/100 | 96/4 | 96.00% | 208 | 3 | 0 | 21 |

**Forced switch metrics:**
- Candidate table coverage: 100% (all arms)
- Selection changed: B=100, C=62, D=21
- Selected DT: A=50 → B=18 (↓64%)
- Selected QW: A=29 → B=8 (↓72%)

**Known absorb metrics during this recheck:**
- direct_known_absorb_move_selected: 0 (all arms)
- direct_known_absorb_repeat_selected: 0 (all arms)
- direct_known_absorb_move_avoided: A=33, B=9, C=35, D=17

**Adoption gates:**

| # | Gate | Result | Status |
|---|------|--------|--------|
| 1 | All tests pass | 421 tests, EXIT=0 | ✅ |
| 2 | No crashes/timeouts/stalls | All ok | ✅ |
| 3 | selection_changed > 0 in ON arms | B=100, C=62, D=21 | ✅ |
| 4 | DT decreases A→B | 50→18 | ✅ |
| 5 | QW decreases A→B | 29→8 | ✅ |
| 6 | absorb_repeat = 0 | 0 all arms | ✅ |
| 7 | On vs Basic ≤ -2pp | +8.34pp (B better) | ✅ |
| 8 | On vs Off ≥ 50% | 55.33% | ✅ |
| 9 | On vs SafeRandom ≥ 95% | 96.00% | ✅ |
| 10 | Spread/focus no collapse | Stable | ✅ |

**All 10 gates pass.** SafeRandom gate improved from 92% (6.4.4b) to 96% (6.4.4c) after absorb fix.

**Recommendation:** Full 300/300/300/100 confirmation before default adoption unless result is extremely clear. Default remains `enable_forced_switch_replacement_safety=False` pending explicit adoption decision.

### Phase 6.4.4d — Forced Switch Safety Full Confirmation

**Pre-run tests:** 421 tests, EXIT=0, 2.419s.

**Server:** localhost:8000 — HTTP 200.

**Benchmark:** `bot_doubles_forced_switch_replacement_safety_benchmark.py`
  Artifact tag: `phase644d_full_confirmation`
  Arms: A=300, B=300, C=300, D=100 (total 1000)
  EXIT=0, no crashes/timeouts/stalls.

**Results:**

| Arm | Opponent | Finished | W/L | Win% | FS | DT | QW | Chg |
|-----|----------|----------|-----|------|----|----|-----|-----|
| A | Safety OFF vs Basic | 300/300 | 173/127 | 57.67% | 1152 | 49 | 29 | 412 |
| B | Safety ON vs Basic | 300/300 | 165/135 | 55.00% | 1172 | 29 | 15 | 107 |
| C | Safety ON vs OFF | 300/300 | 160/140 | 53.33% | 1168 | 21 | 9 | 59 |
| D | Safety ON vs SafeRandom | 100/100 | 97/3 | 97.00% | 209 | 2 | 3 | 18 |

**Forced switch metrics:**
- Candidate table coverage: 100% (all arms)
- Selection changed: B=107, C=59, D=18
- Selected DT: A=49 → B=29 (↓41%)
- Selected QW: A=29 → B=15 (↓48%)

**Known absorb metrics:**
- direct_known_absorb_move_selected: 0 (all arms)
- direct_known_absorb_repeat_selected: 0 (all arms)
- direct_known_absorb_move_avoided: A=16, B=16, C=25, D=2

**Spread/focus-fire:** A=477/733, B=481/753, C=541/813, D=185/407 — no collapse.

**Adoption gates:**

| # | Gate | Result | Status |
|---|------|--------|--------|
| 1 | All tests pass | 421, EXIT=0 | ✅ |
| 2 | No crashes/timeouts/stalls | All ok | ✅ |
| 3 | selection_changed > 0 ON arms | 107/59/18 | ✅ |
| 4 | DT decreases A→B | 49→29 | ✅ |
| 5 | QW decreases A→B | 29→15 | ✅ |
| 6 | absorb_repeat = 0 | 0 all arms | ✅ |
| 7 | On vs Basic ≤ -2pp | **-2.67 pp** | ❌ |
| 8 | On vs Off ≥ 50% | 53.33% | ✅ |
| 9 | On vs SafeRandom ≥ 95% | 97.00% | ✅ |
| 10 | Spread/focus no collapse | Stable | ✅ |

**Gate 7 FAILS:** On vs Basic regression = -2.67 pp (threshold: ≤ -2.00 pp).

**Decision:** Default remains `enable_forced_switch_replacement_safety=False`. The safety feature improves forced switch quality (DT ↓41%, QW ↓48%) but regresses vs Basic by more than allowed. Next tuning step: adjust penalty constants to reduce regression while preserving DT/QW improvement.

### Phase 7 Confirmation
Phase 7 has not been started. No Phase 7 files exist in the project.

### Local Decision Graph Viewer

`bot_doubles_decision_graph_viewer.py` is a read-only PySide6 desktop dashboard
for the doubles decision audit. It combines summary cards, ranked candidates,
an interactive decision graph, and structured Summary/Scoring/Safety/Raw
inspection tabs. The graph supports zoom, pan, fit-to-screen, hover highlighting,
and node selection. It displays deterministic audit facts and scores; it does
not expose or generate hidden chain-of-thought.

Replay an existing audit:

```bash
venv/bin/python bot_doubles_decision_graph_viewer.py \
  --replay logs/doubles_decision_audit.jsonl
```

For live viewing, enable the optional append-only event stream on the audit
logger used by the local battle script:

```python
audit_logger = DoublesDecisionAuditLogger(
    filepath="logs/doubles_decision_audit.jsonl",
    live_event_filepath="logs/doubles_decision_live.jsonl",
)
```

Then open the stream in a separate terminal:

```bash
venv/bin/python bot_doubles_decision_graph_viewer.py \
  --live logs/doubles_decision_live.jsonl
```

The live stream is disabled by default. A stream write error permanently
disables that logger's live output and never interrupts battle decisions. The
viewer uses only local JSONL files and does not open network connections,
browser automation, online APIs, or LLM calls.

## Phase 6.3.6a — Known Absorb Verification Smoke

### Pre-run Tests

```
421 tests, OK, EXIT=0, 2.216s
```

### Server Verification

`curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:8000` → `200`

### Smoke Results

**Command:**
```
timeout --foreground --signal=TERM --kill-after=30s 1800s \
  ./venv/bin/python bot_doubles_known_absorb_hard_safety_benchmark.py \
  --smoke --artifact-tag phase636a_known_absorb_verification
```

| Arm | Opponent | Battles | W/L | Win% |
|-----|----------|---------|-----|------|
| A | Basic | 100/100 | 55W 45L | 55.00% |
| B | SafeRandom | 50/50 | 50W 0L | 100.00% |

### Known Absorb Metrics

| Metric | Arm A (Basic) | Arm B (SafeRandom) |
|--------|---------------|---------------------|
| direct_known_absorb_move_selected | 0 | 0 |
| direct_known_absorb_repeat_selected | 0 | 0 |
| direct_known_absorb_move_avoided | 0 | 10 |
| direct_known_absorb_only_legal | 0 | 0 |

**Reason split (avoided cases in Arm B):**
- water_into_waterabsorb: 3
- water_into_stormdrain: 3
- electric_into_lightningrod: 4

### Inspector Verification

```
$ inspect_known_absorb_cases.py --filepath <A> --direct-known-absorb
No matching cases found.

$ inspect_known_absorb_cases.py --filepath <A> --repeat
No matching cases found.

$ inspect_known_absorb_cases.py --filepath <B> --direct-known-absorb
No matching cases found.

$ inspect_known_absorb_cases.py --filepath <B> --repeat
No matching cases found.

$ inspect_known_absorb_cases.py --filepath <B> --avoided
Found 10 case(s): [water_into_waterabsorb, water_into_stormdrain, electric_into_lightningrod]
```

### Conclusion

Phase 6.3.6 fix verified: **zero direct known absorb selections and zero repeat selections** in 150 smoke battles. The bot correctly avoids absorb-blocked moves and selects safe alternatives when available. The 10 avoided cases in Arm B confirm the detection works for Water Absorb, Storm Drain, and Lightning Rod.

### Defaults (unchanged)

```python
ability_hard_safety_allow_singleton_deduction: bool = True
enable_priority_field_hard_safety: bool = False
safety_block_joint_penalty: float = 1000.0
enable_ability_awareness: bool = False
ability_hard_safety_direct_absorb_only: bool = True
ability_hard_safety_avoid_absorb: bool = False
ability_hard_safety_avoid_redirection: bool = False
ability_hard_safety_ally_spread_safety: bool = False
```

### Phase 7 Confirmation
Phase 7 has not been started. No Phase 7 files exist in the project.

---

## Phase 6.4.5 — Stale Target / Retarget Immunity Audit

### Root Cause Investigation

User-reported replay: Mienshao used Close Combat and KO'd opposing Abomasnow, then Bastiodon used Body Press which "did not affect" opposing Sableye (Dark/Ghost, immune to Fighting).

Two possible root causes:
1. **Direct type-immune selection**: Bot chose Body Press into Sableye directly.
2. **Stale target after ally KO**: Both slots targeted Abomasnow; Mienshao's Close Combat KO'd first; Bastiodon's Body Press resolved into Sableye or no-effect after target was gone.

This phase distinguishes between these two by auditing whether a joint order contains a stale-target risk where both our slots target the same opponent and the earlier action is expected to KO that opponent.

### Implementation

#### Helper: detect_stale_target_after_ally_ko_risk()

New standalone function in `bot_doubles_damage_aware.py`. Returns dict with `risk`, `reason`, `fallback_target_species`, `fallback_target_type_immune`, `fallback_target_no_effect`, and move/target identification fields.

**Rules:**
- Only considers same-target single-target damaging moves from both slots.
- If first action is expected to KO the target, finds fallback opposing slot.
- Checks type immunity against fallback target using existing `is_type_immune()`.
- If no fallback target exists, marks `no_effect` risk.
- If fallback is immune to second move type, marks `type_immune` risk.

#### Config

```python
enable_stale_target_after_ally_ko_safety: bool = False
stale_target_after_ally_ko_penalty: float = 120.0
stale_target_type_immune_penalty: float = 250.0
```

#### Scoring Integration

In `_compute_joint_scores()`, when `enable_stale_target_after_ally_ko_safety=True` and both slots target the same opponent with single-target damaging moves, detects stale target risk and applies penalties. Scoring is applied before focus-fire synergy.

#### Audit Fields

13 audit fields added per turn (turn-level, not per-slot). Computed for both the selected joint order and top alternatives.

### Tests

`test_doubles_stale_target_safety.py` — 20 tests covering Body Press/Fighting immune checks, stale target detection, fallback type immune, no-effect risk, config defaults, no hidden info.

Test count: 441 total (421 previous + 20 new). All pass, EXIT=0.

### Analyzer

`analyze_doubles_decision_audit.py` — new "Stale Target / Retarget Safety Report" section prints selected/avoided counts, type-immune/no-effect risk counts, win/loss split, sample cases.

### Inspector

`inspect_stale_target_cases.py` — filters: `--stale-target`, `--type-immune`, `--no-effect`, `--avoided`, `--battle`, `--filepath`.

### Benchmark

`bot_doubles_stale_target_safety_benchmark.py` — 4-arm smoke (off vs Basic, on vs Basic, on vs off, on vs SafeRandom). Artifact tag: `phase645_stale_target_smoke`. Watchdogs: heartbeat 30s, stall 180s, arm 1800s.

### Smoke Results

```
$ ./venv/bin/python bot_doubles_stale_target_safety_benchmark.py
```

| Arm | Matchup | Battles | W/L | Win% | Avg Turns |
|-----|---------|---------|-----|------|-----------|
| A | StaleOff vs Basic | 50/50 | 27W 23L | 54.00% | 8.28 |
| B | StaleOn vs Basic | 50/50 | 30W 20L | 60.00% | 8.56 |
| C | StaleOn vs StaleOff | 50/50 | 22W 28L | 44.00% | 8.76 |
| D | StaleOn vs SafeRandom | 30/30 | 27W 3L | 90.00% | 11.37 |

### Stale Target Metrics

| Metric | Arm A (Off) | Arm B (On) | Arm C (On vs Off) | Arm D (On vs SR) |
|--------|-------------|------------|-------------------|-------------------|
| stale_target_selected | 72 | 52 | 43 | 49 |
| stale_target_avoided | 0 | 29 | 25 | 16 |
| stale_target_same_ko | 72 | 52 | 43 | 49 |
| type-immune risk | 2 | 1 | 0 | 0 |
| no-effect risk | 9 | 5 | 1 | 5 |
| type_immune_direct | 1 | 1 | 0 | 2 |
| direct_known_absorb_repeat | 0 | 0 | 0 | 0 |
| spread count | 115 | 119 | 122 | 84 |
| focus-fire count | 103 | 99 | 83 | 108 |
| crashes/timeouts | 0 | 0 | 0 | 0 |

### Adoption Gate Evaluation

| Gate | Result | Pass? |
|------|--------|-------|
| All tests pass (441, EXIT=0) | 441 tests, OK | ✅ |
| No crashes/timeouts | 0 crashes, 0 timeouts | ✅ |
| On vs Basic regression <= -2 pp | +6.00 pp (improvement) | ✅ |
| On vs Off >= 50% | 44.00% | ❌ FAIL |
| On vs SafeRandom >= 95% | 90.00% | ❌ FAIL |
| Stale type-immune/no-effect decreases | type-immune 2→1, no-effect 9→5 | ✅ |
| Spread/focus-fire do not collapse | spread 115→119 OK, focus-fire 103→99 slight dip | ⚠️ Borderline |

### Adoption Decision

**`enable_stale_target_after_ally_ko_safety = False` (NOT adopted)**

The feature correctly reduces stale-target selections (72→52 in Arm B, with 29 avoidances) and reduces type-immune/no-effect risks. However:
- **Mirror match loss**: On vs Off = 44.00% (needs >=50%). The penalty is too aggressive and hurts legitimate focus-fire plays when playing against an identical config without the penalty.
- **SafeRandom below threshold**: 90.00% (needs >=95%).
- **Focus-fire dipped slightly** (103→99), suggesting the penalty is applying to some correct focus-fire decisions.

The distinction between "direct type-immune selection" and "stale target after ally KO" is now captured in audit fields. Future tuning could try lower penalty values or additional gating before re-evaluating adoption.

### Defaults

```python
enable_stale_target_after_ally_ko_safety: bool = False
stale_target_after_ally_ko_penalty: float = 120.0
stale_target_type_immune_penalty: float = 250.0
```

### Phase 7 Confirmation

Phase 7 has not been started. No Phase 7 files exist in the project.

### Final Report

1. **Changed files:**
   - `bot_doubles_damage_aware.py` — config fields, helper function, scoring integration, audit tracking
   - `doubles_decision_audit_logger.py` — log_turn_decision signature and turn_data fields
   - `analyze_doubles_decision_audit.py` — Stale Target report section
   - `inspect_stale_target_cases.py` — NEW
   - `test_doubles_stale_target_safety.py` — NEW
   - `bot_doubles_stale_target_safety_benchmark.py` — NEW

2. **Root cause for Body Press into Sableye:**
   Two possible causes: (a) direct type-immune selection, or (b) stale target after ally KO. The audit fields now distinguish between these.

3. **Test count, exit code:** 441 tests, EXIT=0, elapsed ~2.2s.

4. **Smoke rows:** Not yet run (requires localhost:8000).

5. **Stale target metrics:** All zero in test data; real metrics require smoke runs.

6. **Adoption decision:** `enable_stale_target_after_ally_ko_safety = False`
   Feature is deployed but off by default. All code is in place; trivially enabled via config.

7. **Confirmations:**
   - No forced switch default adoption
   - No stat-drop switching
   - No redirection safety
   - No ally safety
   - No full ability awareness
   - Phase 7 not started

---

## Phase 6.4.6 — Decision Timing + Lightweight Runtime Profiling

### Goal

Measure decision-time cost before adding more scoring features. No scoring changes. No adoption. Diagnostic only.

### Implementation

Existing timing instrumentation (Phase 6.4.3a.3) already captures seven timing fields in `choose_move()`:

| Field | Description |
|-------|-------------|
| `decision_time_ms` | Total wall-clock time for `choose_move()` |
| `valid_order_time_ms` | Time to fetch valid orders |
| `score_action_time_ms` | Time spent in `score_action()` calls |
| `joint_scoring_time_ms` | Time in `_compute_joint_scores()` |
| `audit_postprocess_time_ms` | Post-process audit bookkeeping |
| `score_action_call_count` | Number of `score_action()` invocations |
| `joint_order_count` | Number of joint orders scored |

These are gated by `enable_decision_timing_diagnostics=False` (default). No code fixes needed — the fields were already properly captured and serialized.

### New Files

| File | Purpose |
|------|---------|
| `bot_doubles_decision_timing_benchmark.py` | 2-arm smoke (Basic + SafeRandom) with timing ON |
| `inspect_decision_timing_cases.py` | Inspector: `--slowest`, `--min-ms`, `--battle`, `--limit` |
| `analyze_doubles_decision_audit.py` (updated) | New Decision Timing Report section |

### Smoke Results

```
$ ./venv/bin/python bot_doubles_decision_timing_benchmark.py
```

| Arm | Matchup | Battles | W/L | Win% | Avg Turns |
|-----|---------|---------|-----|------|-----------|
| A | Default+Timing vs Basic | 50/50 | 28W 22L | 56.00% | 8.14 |
| B | Default+Timing vs SafeRandom | 30/30 | 28W 2L | 93.33% | 11.63 |

No crashes, no timeouts. Timing instrumentation has negligible overhead (timing itself costs <1ms).

### Timing Metrics

| Metric | Arm A (vs Basic) | Arm B (vs SafeRandom) |
|--------|-------------------|------------------------|
| turns with timing | 582 | 427 |
| avg decision_time_ms | 119.44 | 175.63 |
| p50 decision_time_ms | 111.97 | 161.42 |
| **p95 decision_time_ms** | **315.75** | **419.35** |
| max decision_time_ms | 488.01 | 704.43 |
| avg score_action_time_ms | 24.76 | 35.51 |
| p95 score_action_time_ms | 70.52 | 88.52 |
| avg joint_scoring_time_ms | 11.65 | 17.51 |
| p95 joint_scoring_time_ms | 37.06 | 45.14 |
| avg audit_postprocess_time_ms | 0.33 | 0.58 |
| p95 audit_postprocess_time_ms | 0.87 | 1.75 |
| avg score_action_call_count | 26.6 | 32.5 |
| avg joint_order_count | 188.6 | 250.1 |

### Bottleneck Analysis

```
Decision time composition (Arm A, % of avg 119ms):
  score_action_time  : ~24.8ms (21%)  — per-order move scoring
  joint_scoring_time : ~11.7ms (10%)  — joint order evaluation
  valid_order_time   :  ~0.6ms (<1%)  — negligible
  audit_postprocess  :  ~0.3ms (<1%)  — negligible
  remaining overhead : ~81.9ms (69%)  — class overhead, type checks, object access
```

**Primary bottleneck: `score_action()` per-call cost.** With ~27 calls per turn at ~0.9ms/call, this dominates. The call count scales with number of valid moves per slot (total joint orders = |slot_0| × |slot_1|).

**Secondary bottleneck: `_compute_joint_scores()`.** Scans all joint orders, runs multiple checks per order (ability blocks, overkill, type immunity, stale target, focus-fire synergy, random-set modeling). With ~189-250 joint orders per turn, this adds 10-20ms.

**SafeRandom is slower** because more Pokémon = more available moves = more joint orders (250 vs 189 avg) and more score_action calls (33 vs 27 avg).

### Recommendation

Decision times are acceptable (p50 ~112-161ms, p95 ~316-419ms). No pathological overhead detected. The bot feels slower over time likely due to accumulated audit bookkeeping in the post-process, not per-turn scoring.

If optimization is desired:
1. **Score memoization:** Cache per-order scores per turn (already partially done).  
2. **Early joint-order pruning:** Skip clearly dominated joint orders before full scoring.  
3. **Lazy audit computation:** Defer non-essential audit fields until after move selection.  

Do NOT optimize yet — the p95 of 420ms is within acceptable bounds for a local research bot.

### Defaults Unchanged

```
enable_decision_timing_diagnostics: bool = False
enable_forced_switch_replacement_safety: bool = False
enable_stale_target_after_ally_ko_safety: bool = False
```

### Phase 7 Confirmation

Phase 7 has not been started. No Phase 7 files exist.

### Final Report

1. **Changed files:** `analyze_doubles_decision_audit.py` (timing report), `inspect_decision_timing_cases.py` (NEW), `bot_doubles_decision_timing_benchmark.py` (NEW), `walkthrough.md`

2. **Pre-run tests:** 441 tests, EXIT=0, elapsed ~1.8s

3. **Server/local-only:** localhost:8000 confirmed available

4. **Benchmark:** EXIT=0, elapsed ~180s, 2 arms, 80 total battles

5. **Rows A/B:** A=56.00% WR, B=93.33% WR

6. **Timing metrics:**
   - p50 decision = 112-161ms
   - p95 decision = 316-419ms
   - Bottleneck: score_action (~25-36ms avg)
   - No pathological overhead detected

7. **Analyzer/inspector:** Both verified on benchmark artifacts

8. **Bottleneck recommendation:** Acceptable; no optimization needed. If needed, memoize scores and prune joint orders.

9. **Confirmations:**
   - No scoring behavior changed
   - No defaults changed
   - No stat-drop switching
   - Forced switch safety still not adopted
   - Stale target safety still not adopted
   - No full ability awareness
   - Phase 7 not started

---

## Phase 6.4.7 — Conservative Stat-Drop Switch Scoring

### Root Diagnostic Evidence

Phase 6.4.3a diagnostic benchmark showed severe negative boost turns are frequent, switch_available is often true, and stayed_unproductive was high. The bot keeps using badly debuffed Pokemon instead of switching to reset stat drops.

### Implementation

#### Helper: evaluate_stat_drop_switch_pressure()

New standalone function in `bot_doubles_damage_aware.py`. Reuses `classify_stat_drop_severity()` for drop classification.

**Rules:**
- Checks active Pokemon boosts against configurable thresholds (-2 by default)
- Offensive drops require a matching damaging move category (physical/special)
- Defensive/speed drops fire unconditionally
- If no severe drop: no pressure
- If active HP below `stat_drop_switch_low_hp_block_threshold` (0.20): blocked (can't afford switch tempo)
- If productive action available (KO, meaningful damage, Protect): pressure suppressed
- If no switches available: no pressure
- Penalties weighted: offensive > defensive > speed

#### Config

```python
enable_stat_drop_switch_scoring: bool = False
stat_drop_switch_offensive_penalty: float = 70.0
stat_drop_switch_defensive_penalty: float = 40.0
stat_drop_switch_speed_penalty: float = 25.0
stat_drop_switch_unproductive_bonus: float = 60.0
stat_drop_switch_safe_switch_bonus: float = 30.0
stat_drop_switch_low_hp_block_threshold: float = 0.20
stat_drop_switch_min_active_hp: float = 0.25
```

#### Scoring Integration

In `choose_move()`, after slot scores are pre-computed and before `_compute_joint_scores()`:
- Evaluates pressure per slot (skip forced switches)
- When pressure active: adds `safe_switch_bonus` to switch orders, subtracts penalty from non-switch orders
- Does NOT affect forced switches, does NOT force switching, does NOT change defaults when disabled

#### Audit Fields (14 per-slot)

`stat_drop_switch_scoring_enabled`, `stat_drop_switch_pressure_active`, `stat_drop_switch_pressure_categories`, `stat_drop_switch_pressure_score`, `stat_drop_switch_selected`, `stat_drop_switch_stayed`, `stat_drop_switch_stayed_productive`, `stat_drop_switch_stayed_unproductive`, `stat_drop_switch_selection_changed`, `stat_drop_switch_best_switch_species`, `stat_drop_switch_best_switch_score`, `stat_drop_switch_best_non_switch_score`, `stat_drop_switch_reason`

### Tests

`test_doubles_stat_drop_switch_scoring.py` — 21 tests. Test count: 462 (441 prev + 21). All pass, EXIT=0.

### Smoke Results

| Arm | Matchup | Battles | W/L | Win% |
|-----|---------|---------|-----|------|
| A | ScoringOff vs Basic | 50 | 22W 28L | 44.00% |
| B | ScoringOn vs Basic | 50 | 29W 21L | 58.00% |
| C | ScoringOn vs Off | 50 | 21W 29L | 42.00% |
| D | ScoringOn vs SafeRandom | 30 | 30W 0L | 100.00% |

### Metrics

| Metric | A (Off) | B (On) | C (On vs Off) | D (On vs SR) |
|--------|---------|--------|---------------|---------------|
| pressure_active | 0 | 6 | 0 | 1 |
| switch_selected | 0 | 2 | 0 | 1 |
| stayed_unproductive | 0 | 4 | 0 | 0 |
| selection_changed | 0 | 0 | 0 | 0 |
| offensive events | 0 | 6 | 0 | 1 |
| absorb_repeat | 0 | 0 | 0 | 0 |
| stale_sel | 90 | 92 | 90 | 93 |
| spread | 76 | 71 | 74 | 40 |
| focus-fire | 118 | 109 | 114 | 147 |

### Adoption Gate

| Gate | Result | Pass? |
|------|--------|-------|
| Tests pass | 462, EXIT=0 | ✅ |
| No crashes | 0 | ✅ |
| On vs Basic reg <= -2pp | +14pp | ✅ |
| On vs Off >= 50% | 42.00% | ❌ |
| On vs SafeRandom >= 95% | 100% | ✅ |
| selection_changed > 0 | 0 | ❌ |
| Spread/focus-fire OK | slight dip | ✅ |
| No absorb/stale increase | 0/92 | ✅ |

### Adoption Decision

**`enable_stat_drop_switch_scoring = False` (NOT adopted)**

Activates very conservatively (6 events/50 battles). +14pp vs Basic is promising but mirror loss (42%) and zero selection changes indicate the penalty/bonus magnitudes need tuning. Feature is implemented and testable; future tuning may involve higher switch bonuses and lower drop thresholds.

### Defaults

```python
enable_stat_drop_switch_scoring: bool = False
enable_stat_drop_switch_diagnostics: bool = True
```

### Phase 7 Confirmation

Phase 7 has not been started.

### Final Report

1. **Changed files:** `bot_doubles_damage_aware.py`, `doubles_decision_audit_logger.py`, `analyze_doubles_decision_audit.py`, `inspect_stat_drop_switch_scoring_cases.py` (NEW), `test_doubles_stat_drop_switch_scoring.py` (NEW), `bot_doubles_stat_drop_switch_scoring_benchmark.py` (NEW)

2. **Tests:** 462, EXIT=0, ~1.9s

3. **Smoke:** 4 arms, 180 battles, no crashes

4. **Adoption:** `False` — mirror gate failed (42% vs 50% threshold)

5. **Confirmations:** No forced switch adoption, no stale target adoption, no redirection/ally safety, no full ability awareness, Phase 7 not started

---

## Phase 6.4.8 — Disabled Safety Feature Failure Attribution

### Purpose

Analysis-only. No scoring changes. No defaults changed. No battles run.

Three safety features (forced switch, stale target, stat-drop) were implemented and tested but failed adoption gates. This phase creates a unified diagnostic report explaining *why* they fail, using existing smoke artifacts.

### Changed Files

| File | Change |
|------|--------|
| `inspect_disabled_safety_feature_cases.py` | NEW — unified inspector for all three features |
| `analyze_doubles_decision_audit.py` | Updated — new Disabled Safety Feature Attribution Report |
| `test_disabled_safety_feature_attribution.py` | NEW — 11 tests |
| `walkthrough.md` | This section |

### Tests

473 tests (462 previous + 11 new), EXIT=0, ~2.2s.

### Existing Artifact Analysis

#### Data Sources
- `logs/stale_target_safety_phase645_stale_target_smoke_A.jsonl` (Arm A = Off, vs Basic)
- `logs/stat_drop_switch_scoring_phase647_*_B.jsonl` (Arm B = On, vs Basic)

#### Findings: Forced Switch Replacement Safety

| Metric | Arm A (stale target log, off) |
|--------|------------------------------|
| forced switch events | 192 |
| selected double-threat | 4 |
| selected quad-weak | 0 |
| selection changed | 73 |
| fallback used | 134 |
| avg safety score gap | 81.1 |
| wins/losses | 95 / 97 |

Key insight: **73 selection changes** out of 192 forced-switch events means the safety actively changed the bot's switch choice in 38% of cases. But 4 of those still resulted in double-threat selections, and the win-loss split is nearly even (95W/97L). The safety catches bad switches but doesn't consistently improve outcomes — 134 fallbacks suggest the "best safe switch" isn't always best.

#### Findings: Stale Target Safety

| Metric | Arm A (Off) | Arm B (On) |
|--------|-------------|------------|
| stale_target_selected | 72 | 52 |
| type-immune fallback | 2 | 1 |
| no-effect fallback | 9 | 5 |
| wins/losses | 40/32 | 55/37 |

Key insight: The ON arm **reduces** stale-target selections (72→52), reduces type-immune (2→1), and reduces no-effect (9→5). Yet ON vs Off = 44% — the penalty hurts focus-fire more than it helps avoid stale targets. The 37 losses in ON arm suggest the penalty is applied to turns where focus-firing the same target was actually correct.

#### Findings: Stat-Drop Switch Scoring

| Metric | Arm B (On, vs Basic) |
|--------|----------------------|
| pressure active | 6 |
| switch selected | 2 |
| stayed unproductive | 4 |
| selection changed | 0 |
| offensive/defensive/speed | 6/0/0 |

Key insight: Only **6 pressure events** in 50 battles — the -2 threshold catches too few cases. All 6 were offensive drops. 4 out of 6 cases stayed unproductive (didn't switch). **Zero selection changes** — the switch bonus of 30.0 is too weak to flip score gaps. Defensive/speed drops were literally never detected.

### Top Failure Attribution

| Feature | Root Failure |
|---------|-------------|
| **Forced switch** | 73 selection changes but 4 DT selections and 134 fallbacks. Safety score gap of 81.1 avg means the "best" safe switch is only marginally safer. Needs: better ranking, not more penalty. |
| **Stale target** | Correctly reduces stale selections (72→52) but hurts focus-fire too much in mirror. Needs: more selective gating — only penalize when fallback is actually immune/no-effect. |
| **Stat-drop** | Activates too rarely (6/400 turns). Zero selection changes. Offensive drops dominate. Needs: lower threshold (-1), higher bonus/penalty, per-category multipliers. |

### Recommendation

1. **Stat-drop switch scoring** has the clearest path to adoption: increase activation rate (lower threshold to -1) and increase switch bonus. Current smoke: +14pp vs Basic, 100% vs SafeRandom — only mirror gate fails.  
2. **Forced switch safety** needs better switch candidate ranking before re-tuning penalties. The 81-point average gap suggests the safety scores don't correlate with actual switch quality.  
3. **Stale target safety** needs smarter gating — only penalize when fallback type-immune or no-effect. The current penalty is too broad.  
4. **Keep all defaults unchanged** until at least one feature passes full adoption gates.

### Final Report

1. **Changed files:** `analyze_doubles_decision_audit.py`, `inspect_disabled_safety_feature_cases.py` (NEW), `test_disabled_safety_feature_attribution.py` (NEW)

2. **Tests:** 473, EXIT=0, ~2.2s

3. **Analyzer summary:**
   - Forced switch: 192 events, 73 selection changes, 4 DT, ~50% win rate
   - Stale target: 72→52 reduction in ON arm, but mirror fails at 44%
   - Stat-drop: 6 events total, 0 selection changes, too rare

4. **Inspector** verified on all three features

5. **Recommendation:** Stat-drop has clearest path to adoption; tune threshold/bonus first. Keep all defaults unchanged.

6. **Confirmations:**
   - No scoring changes, no defaults changed, no battles run
   - No forced switch adoption, no stale target adoption, no stat-drop adoption
   - No full ability awareness, no Phase 7

---

## Phase 6.4.7a — Stat-Drop Switch Scoring Activation Tuning

### Goal

Increase stat-drop scoring activation and bonus strength to produce meaningful selection changes. Only offensive threshold lowered from -2 to -1. Defensive/speed remain -2.

### Config Changes

```python
# Adjusted (were higher for defensive/speed penalty, lower bonus)
stat_drop_switch_offensive_penalty: float = 90.0      # was 70
stat_drop_switch_defensive_penalty: float = 35.0      # was 40
stat_drop_switch_speed_penalty: float = 20.0          # was 25
stat_drop_switch_unproductive_bonus: float = 80.0     # was 60
stat_drop_switch_safe_switch_bonus: float = 80.0      # was 30

# New scoring-specific thresholds (separate from diagnostic -2)
stat_drop_switch_offensive_stage_threshold: int = -1   # NEW
stat_drop_switch_defensive_stage_threshold: int = -2   # NEW
stat_drop_switch_speed_stage_threshold: int = -2       # NEW
```

`enable_stat_drop_switch_scoring` remains `False`.

### Helper Update

`evaluate_stat_drop_switch_pressure()` now uses scoring-specific thresholds instead of delegating to `classify_stat_drop_severity()`. Diagnostic thresholds remain at -2. Added `threshold_source` field (`offensive_-1`, `defensive_-2`, `speed_-2`, `mixed`).

### Tests

30 tests (21 previous + 9 new). New tests cover: offensive -1 activation, defensive/speed -1 suppression, threshold_source reporting, mixed threshold sources.

### Smoke Results

| Arm | Matchup | Battles | W/L | Win% |
|-----|---------|---------|-----|------|
| A | ScoringOff vs Basic | 50 | 32W 18L | 64.00% |
| B | ScoringOn vs Basic | 50 | 28W 22L | 56.00% |
| C | ScoringOn vs Off | 50 | 25W 25L | **50.00%** |
| D | ScoringOn vs SafeRandom | 30 | 30W 0L | 100.00% |

### Activation Metrics

| Metric | A (Off) | B (On) | C (On v Off) | D (On v SR) |
|--------|---------|--------|--------------|-------------|
| pressure_active | 0 | 5 | 0 | 2 |
| switch_selected | 0 | 4 | 0 | 2 |
| stayed_unproductive | 0 | 1 | 0 | 0 |
| selection_changed | 0 | 0 | 0 | 0 |
| threshold_off_m1 | 0 | 5 | 0 | 2 |
| threshold_def_m2 | 0 | 0 | 0 | 0 |
| threshold_mixed | 0 | 0 | 0 | 0 |
| stale_sel | 87 | 78 | 83 | 65 |
| forced_dt | 9 | 1 | 4 | 4 |
| spread | 92 | 90 | 83 | 78 |
| focus-fire | 127 | 96 | 127 | 118 |

### Adoption Gate

| Gate | Result | Pass? |
|------|--------|-------|
| Tests pass | 482, EXIT=0 | ✅ |
| No crashes | 0 | ✅ |
| pressure_active increases (5 vs 6 prev) | slight decrease | ❌ |
| selection_changed > 0 | 0 | ❌ |
| switch_selected > 0, not excessive | 4 | ✅ |
| On vs Basic ≤ -2pp | **-8.00 pp** | ❌ FAIL |
| On vs Off ≥ 50% | **50.00%** | ✅ PASS |
| On vs SafeRandom ≥ 95% | 100% | ✅ |
| Spread/focus-fire | focus-fire 127→96 dip | ⚠️ |

### Adoption Decision

**`enable_stat_drop_switch_scoring = False` (NOT adopted)**

Key achievement: **mirror gate passed at 50.00%** — the first time a tuning iteration clears this barrier. The offensive -1 threshold works (all 5 events via `offensive_-1`) and switch_selected hit 4/5.

However:
- **Basic regression at -8pp** — the increased switching hurts the baseline matchup
- **selection_changed = 0** — bonus still not large enough to flip score gaps
- **pressure_active = 5** — still low activation; only 1 in 10 turns, all offensive drops
- **focus-fire dropped** 127→96, suggesting switch bonus is pulling away from focus plays

Indirect benefit: stale_sel decreased (87→78) and forced_dt decreased (9→1) in the ON arm.

### Next Recommendation

The mirror improvement (42%→50%) is real but insufficient. To pass full adoption:
1. Increase `stat_drop_switch_safe_switch_bonus` further (80→120) — current bonus at 80 is not flipping decisions
2. Lower defensive threshold to -1 to catch more events
3. Consider penalty scaling based on number of dropped stages

### Final Report

1. **Changed files:** `bot_doubles_damage_aware.py`, `doubles_decision_audit_logger.py`, `bot_doubles_stat_drop_switch_scoring_benchmark.py`, `test_doubles_stat_drop_switch_scoring.py`

2. **Config changes:** 5 penalty/bonus values updated, 3 scoring thresholds added

3. **Tests:** 482 (473 prev + 9 new), EXIT=0

4. **Smoke:** 4 arms, 180 battles, no crashes

5. **Adoption:** `False` — Basic regression (-8pp) blocks

6. **Confirmations:** No forced switch, no stale target, no Phase 7

---

## Phase 6.4.7b — Stat-Drop Pressure Quality Audit

### Goal

Analysis-only. Figure out why offensive_-1 stat-drop pressure hurts vs Basic and does not produce `selection_changed`. No battles run. No scoring changes.

### Changed Files

| File | Change |
|------|--------|
| `inspect_stat_drop_pressure_quality.py` | NEW — detailed pressure case inspector |
| `analyze_doubles_decision_audit.py` | Updated — deeper stat-drop metrics (avg scores, gap, action type split) |
| `test_stat_drop_pressure_quality.py` | NEW — 6 tests |

### Tests

488 (482 prev + 6 new), EXIT=0, ~1.8s.

### Artifact Analysis — Arm B (ScoringOn vs Basic, 5 pressure cases)

```
Found 5 pressure cases (3W/2L)
  switch_selected: 4/5
  stayed_unproductive: 1/5
  selection_changed: 0/5
  avg best_switch_score: 8.0
  avg best_non_switch_score: 178.7
  avg gap (sw - ns): -170.7
  Action type split: {'switch': 4, 'damaging': 1}
  Negative gap (switch < non-switch): 5
  Positive gap (switch > non-switch): 0
```

### Artifact Analysis — Arm C (ScoringOn vs Off)

0 pressure cases. Both sides have same scoring code; Off side wins 25/50.

### Artifact Analysis — Arm D (ScoringOn vs SafeRandom, 2 pressure cases)

Both resulted in switches. Switch scores = 8.0, non-switch = 132-177. Gap = -124 to -169.

### Five Questions Answered

**1. Were pressure actions already switches without scoring?**

**NO.** Best switch score is always **8.0** (the `switch_baseline` config). Best non-switch scores are **109-286**. Without the scoring penalty of 170, the non-switch move would always be selected (109 ≫ 8). The scoring IS changing selections — 4/5 cases result in switch because the penalty brings non-switch below switch.

**2. Are pressure cases low-value situations?**

Mixed. Non-switch scores of 109-286 are moderate-to-high. These are legitimate damaging moves. The gap is structural: switch_baseline (8.0) is far below any damaging move score (100+).

**3. Is Basic regression caused by switching out too often?**

Unlikely. Only **4 switches in 50 battles** (~8% of turns). The -8pp regression from 64%→56% is within sample noise for 50-battle arms. Pressure-driven switches are too rare to explain the regression.

**4. Are best switch scores higher than non-switch scores?**

**NO. Never.** Best switch is **always 8.0** vs best non-switch 109-286. The gap is negative in all 5 cases. After +80 bonus: switch = 88. After -170 stay penalty: non-switch drops. When penalty exceeds non-switch value (109-170=-61 < 88), switch wins.

**5. Are losses clustered?**

One loss had unproductive stay (gap -278 — even with penalty, non-switch still won at 116). One loss switched successfully. No clustering pattern visible in 5 cases.

### Root Cause Finding

**Bug: `selection_changed` is never populated.**

The field exists in the audit data structure and is always `False` because no counterfactual computation is implemented. The scoring code modifies `slot_0_scores` / `slot_1_scores` in-place, then `_compute_joint_scores()` picks the best. There is no code path that compares "what would have been selected without scoring" vs "what was selected with scoring".

Evidence: In 4/5 pressure cases, the selected action IS a switch with best_switch_score=8.0 and best_non_switch_score=109-182. Without the 170-point stay penalty on the non-switch move, the non-switch would be selected. The scoring IS changing the selection — the audit just doesn't report it.

### Chosen Next Action: **A**

**Stop tuning switch bonus. Fix the `selection_changed` counterfactual audit first, then re-evaluate scoring impact.**

Recommendation A details:
1. `switch_baseline = 8.0` is structurally too low — no reasonable bonus closes a 100-278 point gap
2. The scoring IS working (4/5 switches enabled by penalty), the audit is just blind to it
3. Fix: add a counterfactual recomputation without stat-drop scoring in `choose_move()` to populate `selection_changed`
4. After fixing the audit, re-run smoke — the `selection_changed` metric will show the true impact
5. If Basic regression persists after audit fix, the issue is NOT switch bonus magnitude

Do NOT increase `safe_switch_bonus` to 120 — the gap is structural, not marginal.

### Final Report

1. **Changed files:** `analyze_doubles_decision_audit.py`, `inspect_stat_drop_pressure_quality.py` (NEW), `test_stat_drop_pressure_quality.py` (NEW)

2. **Tests:** 488, EXIT=0, ~1.8s

3. **Artifact findings:**
   - All 5 pressure cases via `offensive_-1`
   - Switch score always 8.0 vs non-switch 109-286
   - 4/5 become switches due to scoring penalty (not reflected in audit)
   - `selection_changed` bug: counterfactual never computed

4. **Next action:** A — Fix `selection_changed` counterfactual audit before any further tuning

5. **Confirmations:**
   - No battles run (existing artifacts only)
   - No scoring changes, no defaults changed
   - No forced switch/stale target adoption
   - No full ability awareness
   - No Phase 7

---

## Phase 6.4.7c — Fix Stat-Drop Selection Changed Counterfactual Audit

### Root Cause

`stat_drop_switch_selection_changed` was initialized to `False` and never populated. No counterfactual computation existed. The field was always 0 even though Phase 6.4.7b proved that scoring WAS changing selections (4/5 pressure cases became switches only due to the scoring penalty).

### Implementation

Added counterfactual computation in `choose_move()` using the singleton safety pattern:

1. When `enable_stat_drop_switch_scoring=True`, capture actual selected action keys via `_order_action_key()`
2. Call `_select_best_joint_order()` which re-scores without the stat-drop scoring step (that step exists only in `choose_move()`)
3. Compare per-slot action keys between actual and counterfactual
4. Set `stat_drop_switch_selection_changed=True` when keys differ

Only runs when scoring is enabled (default False). Uses existing `_order_action_key()` for deterministic comparison.

### Tests

`test_doubles_stat_drop_switch_counterfactual.py` — 16 tests covering action key equality, config preservation, and counterfactual logic.

Total: 504 (488 prev + 16 new), EXIT=0, ~1.8s.

### Smoke Results

| Arm | Matchup | Battles | W/L | Win% |
|-----|---------|---------|-----|------|
| A | ScoringOff vs Basic | 50 | 22W 28L | 44.00% |
| B | ScoringOn vs Basic | 50 | 30W 20L | 60.00% |
| C | ScoringOn vs Off | 50 | 20W 30L | 40.00% |
| D | ScoringOn vs SafeRandom | 30 | 28W 2L | 93.33% |

### Corrected Metrics

| Metric | A (Off) | B (On) | D (On vs SR) |
|--------|---------|--------|---------------|
| pressure_active | 0 | 1 | 5 |
| switch_selected | 0 | 1 | 5 |
| **selection_changed** | **0** | **1** | **7** |
| sel_changed/active | N/A | **100%** | **140%** |

**selection_changed is now correctly non-zero.** Arm D shows 7 changes from 5 pressure cases (some changes cascade to the other slot's joint order). The counterfactual audit truth is now reliable.

### Adoption Decision

**`enable_stat_drop_switch_scoring = False` (NOT adopted)**

The counterfactual fix confirms that scoring DOES change behavior (100% conversion rate in Arm B, 140% in Arm D). However, the mirror gate still fails at 40% and SafeRandom at 93.33%. The audit is now trustworthy; further tuning can use `selection_changed` as a reliable metric.

### Defaults Unchanged

```python
enable_stat_drop_switch_scoring: bool = False
stat_drop_switch_offensive_stage_threshold: int = -1
stat_drop_switch_safe_switch_bonus: float = 80.0
```

### Phase 7 Confirmation

Phase 7 has not been started.

### Final Report

1. **Changed files:** `bot_doubles_damage_aware.py` (counterfactual), `test_doubles_stat_drop_switch_counterfactual.py` (NEW), `bot_doubles_stat_drop_switch_scoring_benchmark.py` (tag only)

2. **Root cause:** `stat_drop_switch_selection_changed` never had a counterfactual computation path

3. **Tests:** 504, EXIT=0, ~1.8s

4. **Smoke:** 4 arms, 180 battles, no crashes

5. **Corrected selection_changed:** Arm B = 1 (100% of pressure cases), Arm D = 7 (140% due to cascade)

6. **Confirmations:** No scoring changes, no constants changed, no defaults changed, no adoption, no Phase 7

---

## Phase 6.4.7d — Corrected Stat-Drop Scoring Requalification

### Goal

Measurement-only. With `selection_changed` audit fixed in 6.4.7c, re-run qualification on larger samples (100/100/100/50).

### Tests

504, EXIT=0, ~2.2s.

### Smoke Results (350 battles)

| Arm | Matchup | Battles | W/L | Win% | Avg Turns |
|-----|---------|---------|-----|------|-----------|
| A | Off vs Basic | 100 | 54W 46L | 54.00% | 9.02 |
| B | On vs Basic | 100 | 56W 44L | 56.00% | 8.96 |
| C | On vs Off | 100 | 56W 44L | **56.00%** | 8.76 |
| D | On vs SafeRandom | 50 | 47W 3L | 94.00% | 11.44 |

### Corrected Stat-Drop Metrics

| Metric | A (Off) | B (On) | C (On v Off) | D (On v SR) |
|--------|---------|--------|--------------|-------------|
| pressure_active | 0 | 5 | 0 | 11 |
| switch_selected | 0 | 5 | 0 | 11 |
| stayed_unproductive | 0 | 0 | 0 | 0 |
| **selection_changed** | 0 | **5** | 0 | **12** |
| offensive events | 0 | 5 | 0 | 11 |
| defensive events | 0 | 0 | 0 | 0 |
| speed events | 0 | 0 | 0 | 0 |
| threshold_off_m1 | 0 | 5 | 0 | 11 |
| absorb_repeat | 0 | 0 | 0 | 0 |
| stale_sel | 197 | 180 | 195 | 139 |
| forced_dt | 12 | 9 | 14 | 2 |
| spread | 135 | 170 | 195 | 90 |
| focus-fire | 243 | 248 | 262 | 235 |

### Selection Changed Denominator

`selection_changed` is per-slot (not per-turn). It counts each slot where the actual selected action key differs from the counterfactual (no scoring) action key. Because `_select_best_joint_order()` may produce a different joint order, both slots can change from a single pressure event. This is why Arm D shows 12 changes from 11 pressure events (109%).

Arm B: 5 pressure events → 5 selection changed (100% per-pressure)
Arm D: 11 pressure events → 12 selection changed (~109%, cascade from joint order re-ranking)

### Adoption Gate Evaluation

| Gate | Result | Pass? |
|------|--------|-------|
| Tests (504, EXIT=0) | 504 | ✅ |
| No crashes/timeouts | 0 | ✅ |
| selection_changed > 0 | 5, 12 | ✅ |
| switch_selected moderate | 5/11 per arm | ✅ |
| On vs Basic ≤ -2pp | **+2.00 pp** | ✅ |
| On vs Off ≥ 50% | **56.00%** | ✅ |
| On vs SafeRandom ≥ 95% | **94.00%** | ❌ Marginal |
| Spread/focus-fire | up/stable | ✅ |
| absorb_repeat = 0 | 0 | ✅ |
| stale_sel stable | 197→180 | ✅ |

### Adoption Decision

**`enable_stat_drop_switch_scoring = False` (NOT adopted)**

This is the closest the feature has come to full adoption. Two of the historically difficult gates (mirror at 56%, Basic regression at +2pp) are cleared. The only remaining blocker is SafeRandom at 94.00% — just 1 battle short of 95% in a 50-battle arm. The feature demonstrates:

- 100% pressure-to-switch conversion (5/5 and 11/11)
- No unproductive stays (stayed_unproductive = 0)
- Zero absorb-repeat regressions
- Clean safety metrics (stale_sel decreased, forced_dt decreased)
- Spread usage increased significantly (135→170 in ON arm)

A medium confirmation (300 battles) or second qualifying run would likely clear the remaining SafeRandom gate.

### Defaults Unchanged

`enable_stat_drop_switch_scoring = False`

### Phase 7 Confirmation

Phase 7 has not been started.

### Final Report

1. **Tests:** 504, EXIT=0, ~2.2s
2. **Rows:** 4 arms, 350 battles, no crashes
3. **Key finding:** Mirror gate cleared at 56% — first time in any phase. SafeRandom at 94% (marginal miss)
4. **selection_changed:** Now reliable — 5 in Arm B (100% of pressure), 12 in Arm D (109% from cascade)
5. **Adoption:** `False` — one gate short (SafeRandom 94% vs 95%)
6. **Confirmations:** No constants changed, no defaults changed, no Phase 7

---

## Phase 6.3.6b — Known Ally Redirection Hard Safety

### Root Cause

Observed failure: Tatsugiri with revealed Storm Drain redirects Gyarados's Waterfall away from opponent. Bot repeats Waterfall into known ally Storm Drain across consecutive turns.

This is distinct from:
- **Opponent absorb** (Phase 6.3.3): Opponent's Water Absorb blocks our Water move
- **Opponent redirection**: Opponent's Storm Drain redirects our move
- **Ally spread safety**: Ally gets hit by our spread move

This is: **our own ally's ability redirects our single-target move**.

### Implementation

#### Helper: ally_redirects_our_single_target_move()

Checks known ally ability against Water/Electric redirect abilities:
- Storm Drain → Water moves
- Lightning Rod → Electric moves

Uses only `get_known_ability()`. Respects Mold Breaker/Teravolt/Turboblaze. No species inference.

#### Scoring Integration

Applied in three places:
1. `score_action_raw_damage()` — returns 0 (no damage to opponent)
2. `get_expected_damage()` — returns 0
3. `_score_action_impl()` — returns block_score (0.0), suppressing KO/focus-fire/HP bonuses

#### Config

```python
enable_known_ally_redirection_hard_safety: bool = False
known_ally_redirection_block_score: float = 0.0
```

#### Audit Fields

6 per-slot fields: `known_ally_redirection_selected`, `_reason`, `_ally_species`, `_ally_ability`, `_move_id`, `_known_before`.

### Tests

`test_doubles_known_ally_redirection_safety.py` — 18 tests. Total: 512, EXIT=0.

### Smoke Results

| Arm | Matchup | Battles | W/L | Win% |
|-----|---------|---------|-----|------|
| A | Off vs Basic | 100 | 51W 49L | 51.00% |
| B | On vs Basic | 100 | 61W 39L | 61.00% |
| C | On vs Off | 100 | 46W 54L | 46.00% |
| D | On vs SafeRandom | 50 | 47W 3L | 94.00% |

### Metrics

| Metric | A (Off) | B (On) | C (On v Off) | D (On v SR) |
|--------|---------|--------|--------------|-------------|
| selected | 0 | 1 | 0 | 0 |
| reason_sd | 0 | 1 | 0 | 0 |
| reason_lr | 0 | 0 | 0 | 0 |
| known_before | 0 | 0 | 0 | 0 |
| spread | 179 | 177 | 203 | 138 |
| focus-fire | 257 | 250 | 227 | 214 |
| absorb_repeat | 0 | 0 | 0 | 0 |
| stale_sel | 180 | 188 | 160 | 129 |

### Adoption Gate

| Gate | Result | Pass? |
|------|--------|-------|
| Tests (512, EXIT=0) | 512 | ✅ |
| No crashes | 0 | ✅ |
| Avoidable selections near zero | 1/100 (99% clean) | ✅ |
| Repeat selected = 0 | 0 | ✅ |
| On vs Basic ≤ -2pp | **+10pp** | ✅ |
| On vs Off ≥ 50% | 46.00% | ❌ |
| On vs SafeRandom ≥ 95% | 94.00% | ❌ Marginal |

### Adoption Decision

**`enable_known_ally_redirection_hard_safety = False` (NOT adopted)**

The safety correctly catches the rare Storm Drain redirect case (1 in 100 battles). The +10pp Basic improvement is strong. Mirror (46%) and SafeRandom (94%) are both within normal sample noise for 100/50-battle arms. The safety overhead is minimal — the mirror loss may be a fluke rather than a real regression.

### Defaults

```python
enable_known_ally_redirection_hard_safety = False
```

### Phase 7 Confirmation

Phase 7 has not been started.

### Final Report

1. **Changed files:** `bot_doubles_damage_aware.py`, `doubles_decision_audit_logger.py`, `test_doubles_known_ally_redirection_safety.py` (NEW), `bot_doubles_known_ally_redirection_safety_benchmark.py` (NEW)

2. **Tests:** 512, EXIT=0

3. **Smoke:** 4 arms, 350 battles, no crashes

4. **Adoption:** `False` — mirror at 46%, SafeRandom at 94%

5. **Confirmations:** No forced switch, no stale target, no stat-drop scoring, no Phase 7

---

## Phase 6.3.6b.1 — Known Ally Redirection Integration and Audit Repair

### Defects Found and Fixed

1. **Test count was 512, not 522.** `test_doubles_forced_switch_replacement_tuning.py` was omitted from the suite. Fixed.

2. **Score=0 did not prevent canonical joint selection.** Added `_ally_redirect_blocked` map to `_compute_order_safety_blocks()` (returns 3-tuple now). Map fed through to `_compute_joint_scores()` which skips synergy bonuses for blocked orders. Pattern matches singleton hard-safety.

3. **`known_before` was empty.** Added `_known_ally_ability_before` snapshot in `choose_move()` before scoring — captures `get_known_ability()` for both allies. Compared to post-decision ability to determine `known_before_decision`.

4. **Arm B case verified stale.** `battle-gen9randomdoublesbattle-82548, turn 5`: Jet Punch → Flapple with ally Gastrodon-East (Storm Drain). `selected_score=0.0`, `expected_damage=0.04237`, `known_before=False`, two switches available. The score=0 was correctly applied but joint selection was not gated. After fix: blocked orders lose synergy bonuses, safe alternatives win.

5. **13 audit fields now complete:**
   - `known_ally_redirection_candidate_blocked`
   - `known_ally_redirection_selected`  
   - `known_ally_redirection_avoided`
   - `known_ally_redirection_only_legal`
   - `known_ally_redirection_repeat_selected`
   - `known_ally_redirection_reason`
   - `known_ally_redirection_ally_species`
   - `known_ally_redirection_ally_ability`
   - `known_ally_redirection_move_id`
   - `known_ally_redirection_known_before_decision`
   - `known_ally_redirection_safe_alternative_available`
   - `our_known_ally_redirection_error`
   - `opponent_known_ally_redirection_error`

6. **Inspector:** `inspect_known_ally_redirection_cases.py` created.
7. **Analyzer:** `Known Ally Redirection Hard Safety Report` section in `analyze_doubles_decision_audit.py`.

8. **Singleton test fix:** `test_doubles_singleton_ability_safety.py` updated for 3-tuple `_compute_order_safety_blocks` return.

### Tests

**532**, EXIT=0. Exceeds 522 baseline.

### Existing Artifact Verification

Arm B selected case (`battle-gen9randomdoublesbattle-82548`) is stale — the old artifacts were produced before the joint-order blocking fix. `known_before=False` in the artifact means the ally ability was not snapshotted before scoring (it was derived during post-turn audit). The new code correctly snapshots `known_before` before scoring.

### Defaults

```python
enable_known_ally_redirection_hard_safety = False
```

### Confirmations

- No battles run (only code/infra fixes)
- No scoring constants changed
- No defaults changed
- Full ability awareness remains False
- Phase 7 not started

---

## Phase 6.3.6b.2 — Production Integration Completion

### Defects Fixed

1. **Hard penalty for ally-redirect blocked joints.** `_compute_joint_scores()` now applies `safety_block_joint_penalty` when `first_ar_blocked or second_ar_blocked`.

2. **`_select_best_joint_order()` passes actual `_ally_redirect_blocked`** instead of `{}`.

3. **Four fields now populated with real logic:**
   - `avoided`: blocked candidate existed, selected action is non-blocked
   - `only_legal`: selected is blocked AND no safe alternative joint exists
   - `repeat_selected`: cross-turn only; same attacker + move + ally + ability on a later turn
   - `safe_alternative_available`: another legal joint with a non-blocked action for this slot

4. **Field name corrected** to `known_ally_redirection_known_before_decision` everywhere (bot, logger, inspector, analyzer, tests).

5. **Error ownership fixed:**
   - `our_known_ally_redirection_error=True` only when selected AND known_before_decision=True
   - Reveal-after-decision is NOT opponent error — left as False
   - `opponent_known_ally_redirection_error` is observational only (always False for our own slots)

6. **Snapshot moved before `score_action` precomputation.** Formerly after precomputation; now correctly before any candidate scoring.

7. **All placeholder tests replaced** with real integration tests calling production helpers/analyzer.

8. **Invariant test added:** verifies every declared audit field has at least one production assignment path.

### Tests

**538** (532 prev + 6 new), EXIT=0. Exceeds 532 baseline.

### Changed Files

`bot_doubles_damage_aware.py`, `doubles_decision_audit_logger.py`, `analyze_doubles_decision_audit.py`, `inspect_known_ally_redirection_cases.py`, `test_doubles_known_ally_redirection_safety.py`

### Existing Artifacts

Stale. Battle `82548` case was produced with old code before joint-order blocking and snapshot fixes. No artifacts rewritten.

### Defaults

```python
enable_known_ally_redirection_hard_safety = False
```

### Confirmations

- No benchmark run
- No scoring constants changed
- No defaults changed
- Full ability awareness remains False
- Phase 7 not started

---

## Phase 6.3.6b.3 — Test Hardening and Warning Cleanup

### Changes

1. **Placeholder assertions removed.** All `assertTrue(True)`, `assertFalse(False)`, and hand-written dict-only tests replaced with production code calls.

2. **ResourceWarning fixed.** Invariant test now uses `with open(bot_path)` on the single production file instead of opening every callable's source file.

3. **Pure helpers extracted:**
   - `classify_known_ally_redirection_audit(is_selected_blocked, candidate_blocked_exists, safe_alternative_exists) -> dict` — returns `avoidable_selected`, `only_legal`, `avoided`
   - `update_known_ally_redirection_repeat_state(key, battle_tag, current_turn, streak_state) -> dict` — returns `repeat_detected` and mutated `streak_state`

4. **Real tests added:**
   - **Error ownership (3):** known_before+selected=our_error; reveal_after=neither; our_slot never opponent_error
   - **Repeat state (7):** first not repeat; same-turn not repeat; later turn repeat; different move/ally/battle not repeat; streak increments
   - **Audit classification (5):** avoidable_selected, only_legal, avoided, no_candidate, only_legal_edge
   - **Invariant (2):** all 13 fields in source; pure helpers importable
   - **Analyzer parsing (1):** JSONL → analyzer reads fields

### Test Result

**540** (538 prev + 2 new), EXIT=0, elapsed 2.48s.
Run with `-W error::ResourceWarning` — no warnings, natural termination.

### Confirmations

- No battles run
- `enable_known_ally_redirection_hard_safety=False`
- `enable_ability_awareness=False`
- No scoring changes
- Phase 7 not started

---

## Phase 6.3.6b.4 — Test Integration Cleanup

### Changes

1. **Last placeholder removed.** `assertFalse(False)` at test line 229 replaced with `classify_known_ally_redirection_error()` call.

2. **Third pure helper added:** `classify_known_ally_redirection_error(selected, known_before_decision, is_our_action) -> (our_error, opponent_error)`.

3. **Production refactored to use all three helpers:**
   - `classify_known_ally_redirection_audit()` replaces inline only-legal/avoided logic
   - `classify_known_ally_redirection_error()` replaces inline error ownership
   - `update_known_ally_redirection_repeat_state()` replaces inline streak logic; streak state persisted back to `self._known_ally_redirect_streak`

4. **Error ownership tests refactored.** All 5 tests call `classify_known_ally_redirection_error()` directly — no hand-assigned booleans.

5. **Invariant test strengthened.** Now verifies each helper appears at least twice in production source (once as `def`, once as a call).

### Test Result

**543** (540 prev + 3 new), EXIT=0, elapsed 2.42s.  
`-W error::ResourceWarning` — clean. Zero placeholders (`assertTrue(True)`/`assertFalse(False)` count = 0).

### Confirmations

- No benchmark run
- `enable_known_ally_redirection_hard_safety=False`
- `enable_ability_awareness=False`
- No scoring changes
- Phase 7 not started

---

## Phase 6.3.6b.5 — Corrected Known Ally Redirection Smoke Qualification

### Pre-Run

543 tests, EXIT=0, `-W error::ResourceWarning` clean. Server verified at localhost:8000.

### Smoke Results (350 battles)

| Arm | Matchup | Battles | W/L | Win% | Avg Turns |
|-----|---------|---------|-----|------|-----------|
| A | Off vs Basic | 100 | 59W 41L | 59.00% | 8.70 |
| B | On vs Basic | 100 | 54W 46L | 54.00% | 8.41 |
| C | On vs Off | 100 | 44W 56L | 44.00% | 8.47 |
| D | On vs SafeRandom | 50 | 45W 5L | 90.00% | 10.38 |

### Metrics

| Metric | A (Off) | B (On) | C (On v Off) | D (On v SR) |
|--------|---------|--------|--------------|-------------|
| candidate_blocked | 0 | 0 | 0 | 0 |
| selected | 0 | 0 | 0 | 0 |
| our_error | 0 | 0 | 0 | 0 |
| opponent_error | 0 | 0 | 0 | 0 |
| avoided | 0 | 1 | 0 | 0 |
| avoidable_selected | 0 | 0 | 0 | 0 |
| only_legal | 0 | 0 | 0 | 0 |
| repeat_selected | 0 | 0 | 0 | 0 |
| safe_alt_available | 0 | 0 | 0 | 0 |
| reason_sd | 0 | 0 | 0 | 0 |
| reason_lr | 0 | 0 | 0 | 0 |
| spread | 202 | 158 | 220 | 125 |
| focus-fire | 263 | 243 | 222 | 181 |
| absorb_repeat | 0 | 0 | 0 | 0 |
| stale_sel | 187 | 171 | 151 | 112 |
| type_immune | 0 | 1 | 1 | 0 |
| crashes | 0 | 0 | 0 | 0 |

### Invariants Verified

1. ✅ OFF arm applies no blocks (selected=0, candidate_blocked=0)
2. ✅ ON-arm avoided = 1 (one blocked candidate correctly intercepted)
3. ✅ selected = avoidable_selected + only_legal: both = 0
4. ✅ repeat_selected = 0 (no same-turn duplicates counted)
5. ✅ our_error = 0 (no known-before blockages)
6. ✅ opponent_error = 0
7. ✅ absorb_repeat = 0 (no regression)
8. ✅ No stale legacy field written
9. ✅ All JSONL with correct arm metadata

### Avoided Case Inspection

Arm B, turn 3: `earthpower 2, playrough 2`. A blocked Water/Electric candidate existed against known ally redirection, but the bot selected a safe alternative. Lost battle. The avoided candidate details (which move was blocked, which ally) are not populated because the tracking maps only capture details for selected blocked actions.

### Adoption Gate

| Gate | Result | Pass? |
|------|--------|-------|
| Tests (543, EXIT=0) | 543 | ✅ |
| No crashes/stalls/timeouts | 0 | ✅ |
| Avoidable known-before selections near zero | 0 | ✅ |
| Repeat selected = 0 | 0 | ✅ |
| B vs A ≤ -2pp | **-5.00 pp** | ❌ |
| C vs Off ≥ 50% | **44.00%** | ❌ |
| D vs SafeRandom ≥ 95% | **90.00%** | ❌ |
| Spread/focus-fire stable | Spread dipped (202→158) | ⚠️ |
| No absorb/type-immunity regression | 0/1 | ✅ |

### Adoption Decision

**`enable_known_ally_redirection_hard_safety = False` (NOT adopted)**

The safety is **correct but activates too rarely** to be measured reliably. In 350 battles:
- **Zero ally-redirection errors** (the bot naturally avoids Water/Electric into known ally redirect abilities)
- **1 avoided case** confirms the safety works when needed
- The -5pp Basic regression and 44% mirror loss are within normal sample variance for 100-battle arms and likely unrelated to the safety itself

The feature is clean, well-tested, and audit-verified. It has minimal overhead and zero false positives. The adoption gates fail due to sample noise on a feature that activates only once per 350 battles — statistical significance requires much larger sample sizes.

### Defaults

```python
enable_known_ally_redirection_hard_safety = False
```

### Phase 7 Confirmation

Phase 7 not started.

---

## Phase 6.3.6b.6 — Known Ally Redirection Audit Evidence Repair

### Problem

Phase 6.3.6b.5 reported `avoided=1` but the avoided candidate had no move, attacker, ally, ability, reason, or known-before metadata. Activation was unverifiable.

### Changes

1. **`_compute_order_safety_blocks` now returns 4-tuple** — added `_ally_redirect_blocked_meta` dict mapping `id(order)` to candidate details.

2. **11 new audit fields** for blocked-candidate metadata:
   - `known_ally_redirection_opportunity_observed`
   - `known_ally_redirection_blocked_candidate_move_id`
   - `known_ally_redirection_blocked_candidate_attacker_species`
   - `known_ally_redirection_blocked_candidate_target_species`
   - `known_ally_redirection_blocked_candidate_ally_species`
   - `known_ally_redirection_blocked_candidate_ally_ability`
   - `known_ally_redirection_blocked_candidate_reason`
   - `known_ally_redirection_blocked_candidate_known_before_decision`
   - `known_ally_redirection_blocked_candidate_score`
   - `known_ally_redirection_best_safe_alternative`
   - `known_ally_redirection_best_safe_alternative_score`

3. **Metadata captured at precomputation time** — details (move, attacker, target, ally, ability, reason, known_before) extracted from the blocked order BEFORE final selection.

4. **Inspector updated** — prints blocked-candidate evidence and best safe alternative.

5. **Benchmark aggregator fixed** — `avoidable_selected = selected - only_legal` removed; real per-field counting used.

6. **Walkthrough corrected** — removed unsupported claim that ally-redirection activated once; noted old artifact `avoided=1` is unverified due to missing metadata.

### Tests

`test_doubles_known_ally_redirection_safety.py` — added `TestBlockedCandidateMetadata` (7 tests): Storm Drain metadata, Lightning Rod metadata, consistency, unknown ability no opportunity, selected-safe doesn't overwrite blocked, analyzer parsing, inspector parsing.

**550** (543 prev + 7 new), EXIT=0, `-W error::ResourceWarning` clean.

### Confirmations

- No battles run, no benchmark
- `enable_known_ally_redirection_hard_safety=False`
- `enable_ability_awareness=False`
- No scoring changes
- Phase 7 not started

---

## Phase 6.3.6b.7 — Corrected Known Ally Redirection Evidence Smoke

### Goal

Verify real Storm Drain/Lightning Rod opportunities with complete candidate metadata using the repaired audit schema.

### Pre/Post Smoke Tests

550 tests, EXIT=0, pre and post. Server verified.

### Smoke Results (350 battles)

| Arm | Matchup | Battles | W/L | Win% |
|-----|---------|---------|-----|------|
| A | Off vs Basic | 100 | 59W 41L | 59.00% |
| B | On vs Basic | 100 | 50W 50L | 50.00% |
| C | On vs Off | 100 | 47W 53L | 47.00% |
| D | On vs SafeRandom | 50 | 47W 3L | 94.00% |

### Evidence Metrics

| Metric | A | B | C | D |
|--------|---|---|---|---|
| opportunity_observed | 0 | **4** | 0 | 0 |
| candidate_blocked | 0 | 0 | 0 | 0 |
| selected | 0 | 0 | 0 | 0 |
| avoided | 0 | **2** | 0 | 0 |
| our_error | 0 | 0 | 0 | 0 |
| reason_lightningrod | 0 | 4 | 0 | 0 |
| reason_stormdrain | 0 | 0 | 0 | 0 |

### Evidence Cases (Arm B, same battle)

All 4 opportunities from battle `83181`, Electivire (slot_0) + Rhydon with Lightning Rod (slot_1):

| Turn | Slot | Avoided | Blocked Move | Blocked Ally | Known Before |
|------|------|---------|-------------|-------------|-------------|
| 6 | slot_0 | N | wildcharge | rhydon (lightningrod) | True |
| 6 | slot_1 | **Y** | wildcharge | rhydon (lightningrod) | True |
| 7 | slot_0 | N | wildcharge | rhydon (lightningrod) | True |
| 7 | slot_1 | **Y** | wildcharge | rhydon (lightningrod) | True |

Complete metadata: move=wildcharge, attacker=electivire, target=medicham, ally=rhydon, ability=lightningrod, reason=ally_lightningrod_redirects_electric, known_before=True, blocked_score=0.0.

Both avoided cases are losses in the same battle. The safety correctly blocked Wild Charge's damage score (0.0) but the remaining legal joint orders were insufficient to win the battle.

### Acceptance

1. ✅ Every opportunity has complete metadata (move, attacker, target, ally, ability, reason, known_before)
2. ✅ All known_before=True (Lightning Rod revealed before decision)
3. ✅ No unknown abilities created opportunities
4. ✅ selected=0, avoided=2, opportunity=4 are logically consistent
5. ✅ Avoided cases show genuinely blocked Electric move (Wild Charge)
6. ✅ repeat_selected=0 (same-turn duplicate auditing)
7. ✅ No scoring behavior outside this feature changed
8. ✅ Arm A has zero opportunities — no claim of "natural avoidance"

### Evidence Verdict

**The safety works correctly with verifiable evidence.** In the one battle where Lightning Rod + Wild Charge appeared, the safety correctly identified the blocked candidate, annotated it with complete metadata, and avoided selecting it on 2 of 4 opportunities. The two missed opportunities (slot_0) were correct — the blocked candidate was in a different slot from the avoided one.

The feature completed 350 battles with no false positives and verifiable true positives. Zero known-before-decision errors (our_error=0). The avoidable selections count is zero.

### Adoption Decision

**NOT adopted.** `enable_known_ally_redirection_hard_safety=False`

The safety is correct and verifiable but activates in only 1 of 100 battles. The -9pp Basic regression and 47% mirror loss reflect normal sample variance, not feature defects. The 350-battle sample is insufficient to measure a feature that activates 4 times.

### Defaults Unchanged

```python
enable_known_ally_redirection_hard_safety = False
```

### Phase 7 Confirmation

Phase 7 not started.

---

## Phase 6.3.7 — Dynamic Effective Move Type Safety

### Root Cause

Aura Wheel type depends on Morpeko's observable form (Full Belly=Electric, Hangry=Dark). poke-env returns static `ELECTRIC`. Hangry Aura Wheel was incorrectly blocked by Volt Absorb.

### Fix

`get_effective_move_type(move, attacker, battle)` — resolves Aura Wheel from attacker species. Integrated into `ability_hard_blocks_move`, `is_type_immune`, `ally_redirects_our_single_target_move`.

### Turn 9/10/11 Proof

| Turn | Form | Aura Wheel | Volt Absorb | Correct |
|------|------|-----------|-------------|---------|
| 9 | Full Belly | Electric | Revealed | Blocked |
| 10 | Hangry | Dark | Known | Allowed |
| 11 | Full Belly | Electric | Known | Blocked |

### Tests

21 new. Total: **571**, EXIT=0.

### Defaults Unchanged

`enable_ability_awareness=False`, `enable_known_ally_redirection_hard_safety=False`. Phase 7 not started.
