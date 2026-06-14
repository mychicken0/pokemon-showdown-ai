# Current Project State

Last verified: 2026-06-13 10:30 (Asia/Bangkok)

This file is the concise handoff document for the current repository state.
Source code and fresh command output take precedence over older reports in
`walkthrough.md`.

## Project

- Repository: `/home/phurin/Program/Showdown_AI/pokemon-showdown-ai`
- Local Showdown server: `/home/phurin/Program/Showdown_AI/pokemon-showdown`
- Battle traffic must remain local to `localhost:8000`.
- Main random-doubles player: `bot_doubles_damage_aware.py`
- Current additional development line: VGC 2026 controlled team preview.
- Phase 7 has not started.

## Random Doubles State

Important adopted defaults include:

```python
enable_ability_hard_safety_only = True
ability_hard_safety_block_score = 0.0
ability_hard_safety_direct_absorb_only = True
ability_hard_safety_allow_singleton_deduction = True

enable_priority_field_hard_safety = False
enable_known_ally_redirection_hard_safety = False
enable_switch_candidate_type_safety = False
enable_forced_switch_replacement_safety = False
enable_stale_target_after_ally_ko_safety = False
enable_stat_drop_switch_scoring = False
enable_support_move_target_hard_safety = False
enable_voluntary_switch_quality_scoring = False

enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
enable_threat_tiebreaker = False
```

Voluntary-switch quality diagnostics exist, but scoring remains disabled.
Forced-switch, stale-target, stat-drop-switch, support-target, and broad
ability-awareness features must not be enabled without new qualification.

## VGC 2026 State

### Verified Results

Phase V2c corrected analysis from the original 450-battle run:

- Controlled `/team` preview selection was implemented.
- Arm B mirror result: 53/100.
- Arm C mirror result: 45/100.
- Arm D basic_top4 result: 103/200 = 51.5%.
- Arm D Wilson 95% CI: approximately 44.6% to 58.3%.
- Aggregate exact binomial p-value: approximately 0.7238.
- Paired outcomes: basic wins both 26, random wins both 23, split 51.
- Paired sign-test p-value: 0.7754496547.
- The policy comparison is inconclusive.
- Phase V3 is **BLOCKED**.
- The earlier V2c statement that Phase V3 was allowed is invalid.

### Artifact Incident

The original raw V2c benchmark artifacts were accidentally truncated:

| Artifact | Current size |
|---|---:|
| `logs/vgc2026_phaseV2c_benchmark.csv` | 195 bytes |
| `logs/vgc2026_phaseV2c_benchmark.jsonl` | 0 bytes |
| `logs/vgc2026_phaseV2c_preview_evidence.csv` | 218 bytes |

The corrected V2c.1 analysis files still exist, but the original raw
450-battle JSONL/CSV evidence is no longer preserved.

The files tagged `phaseV2c2_smoke_test` contain 450 battles:

| Artifact | Records/data rows |
|---|---:|
| benchmark CSV | 450 |
| benchmark JSONL | 450 |
| preview evidence CSV | 900 |

Despite their name, these are a mislabeled full run, not a smoke test.

### V2c.2 Review Result

V2c.2 is **not accepted** yet.

Confirmed improvements:

- 89 discoverable tests.
- Zero skipped tests.
- Zero nested no-op test definitions.
- Artifact tagging and overwrite checks were added.
- Legacy lead evidence is distinguished from an observed-lead field.

Remaining blockers:

1. The exact required unittest command still exits `124` after 10 seconds.
   The process does not terminate naturally.
2. `--smoke` is not passed into benchmark sizing. It ran 450 battles.
3. Some tests instantiate runners with the default `logs/` directory, so unit
   tests can still touch repository artifacts.
4. Observed lead capture depends on `battle.turn == 0`; runtime proof that this
   path captures the first active pair is still missing.
5. `walkthrough.md` currently reports V2c.2 as passing and calls the 450-battle
   run a smoke. That section is stale and must be corrected.

## Phase V2c.3 Review

V2c.3 is a **partial pass, not accepted**.

Verified improvements:

1. Smoke mode is now explicit and no longer inferred from team-pool size.
2. The new smoke has exact arm sizes A=2, B=2, C=2, D1=2, D2=2.
3. The tagged smoke artifacts are structurally correct:

   | Artifact | Verified size |
   |---|---:|
   | benchmark CSV | 11 lines: header + 10 battles |
   | benchmark JSONL | 10 records and 10 unique battle tags |
   | preview evidence CSV | 21 lines: header + 20 player-side rows |

4. Runtime preview evidence contains:

   | Metric | Count |
   |---|---:|
   | observed lead populated | 20/20 |
   | observed lead matched planned lead | 20/20 |
   | mismatch | 0/20 |
   | preview matched plan | 20/20 |

5. Default artifact sizes remain:

   | Artifact | Current size |
   |---|---:|
   | `logs/vgc2026_phaseV2c_benchmark.csv` | 195 bytes |
   | `logs/vgc2026_phaseV2c_benchmark.jsonl` | 0 bytes |
   | `logs/vgc2026_phaseV2c_preview_evidence.csv` | 218 bytes |

6. The prior `phaseV2c2_smoke_test` is correctly declared to be a mislabeled
   450-battle full run.

Remaining blocker:

- The exact required command still exits `124` after 10.01 seconds:

  ```text
  timeout --foreground --signal=TERM --kill-after=5s 10s \
    ./venv/bin/python -m unittest test_vgc2026_controlled_teampreview.py

  EXIT=124
  ```

The report claiming 100 tests, `EXIT=0`, and 0.20 seconds is not confirmed.

Likely lifecycle cause:

- `TestControlledTeampreviewPlayer.setUp()` still constructs a real
  `ControlledTeamPreviewPlayer(...)`, invoking the `poke-env` player lifecycle
  for every test in that class.
- Other tests also directly construct real players.
- The registered cleanup runs only through `atexit`, after normal interpreter
  shutdown has already begun; it does not prevent the observed hang.
- `test_test_cleanup_pattern_available` contains only `pass`, so the claim of
  zero no-op tests is false.

Required correction:

1. Replace all unnecessary real player construction with the existing
   `__new__` fixture helper.
2. Add explicit per-test cleanup for any test that truly requires
   `Player.__init__`.
3. Replace the cleanup placeholder with a behavioral subprocess test.
4. Prove the exact timeout-wrapped command exits 0 naturally.
5. Do not rerun battles; the 10-battle V2c.3 smoke evidence is sufficient for
   smoke semantics and observed-lead validation.

### V2c.3a Lifecycle Result

V2c.3a is **accepted** after independent verification.

The test-only `poke_env_test_cleanup` helper is imported before production
`poke-env` modules in both the main test process and the natural-exit child
process. It unregisters the known hanging
`poke_env.concurrency.__clear_loop` callback. Production battle code does not
import this helper.

Verified result:

```text
Ran 104 tests in 1.423s
OK
EXIT=0 ELAPSED=2.69
```

Verified properties:

- Natural termination under the 10-second foreground timeout.
- Zero `ResourceWarning` under `-W error::ResourceWarning`.
- Zero skipped tests.
- Zero AST-detected pass-only test methods.
- Zero direct `ControlledTeamPreviewPlayer(...)` constructor calls in tests.
- The behavioral child-process import test terminates naturally.
- No additional battles were run for this lifecycle-only correction.
- Default artifact sizes and mtimes remained unchanged:

  | Artifact | Size |
  |---|---:|
  | `logs/vgc2026_phaseV2c_benchmark.csv` | 195 bytes |
  | `logs/vgc2026_phaseV2c_benchmark.jsonl` | 0 bytes |
  | `logs/vgc2026_phaseV2c_preview_evidence.csv` | 218 bytes |

Phase V2c.3 smoke and lifecycle acceptance are now complete. This does not
unblock Phase V3: the V2c policy comparison remains statistically
inconclusive (`p=0.7754496547`).

## Phase V2d.2 Paired Qualification

The corrected `matchup_top4_v2` policy completed a fresh 100-pair,
200-battle qualification against `random`.

Artifact tag:

```text
phaseV2d2_paired_qualification_codex
```

Execution:

```text
Battles: 200/200
Shell EXIT=0
Elapsed: 17.12s
Timeouts/errors/no_battle: 0
CSV records: 200
JSONL records: 200, 200 unique battle tags
Preview evidence: 400 rows
Preview matched plan: 400/400
Observed leads populated: 400/400
```

Policy-normalized results:

| Result | Value |
|---|---:|
| matchup_top4_v2 wins | 102/200 |
| matchup_top4_v2 win rate | 51.0% |
| Wilson 95% CI | 44.1% to 57.8% |
| Aggregate exact p-value | 0.832070 |
| V2 wins both sides | 24 pairs |
| Random wins both sides | 22 pairs |
| Split pairs | 54 |
| Paired two-sided sign-test p-value | 0.882996 |

Arm perspective:

- D1: `matchup_top4_v2` as player won 57/100.
- D2: `random` as player won 55/100, so `matchup_top4_v2` won 45/100.

Decision:

- Artifact, preview, chronology, and pairing gates pass.
- The point estimate favors V2 only slightly: 51.0%.
- The paired result is not statistically significant.
- Phase V3 remains **BLOCKED**.
- Do not repeat the same benchmark merely to chase significance. The next
  policy iteration should address why the advantage disappears when V2 is on
  the D2/opponent side, then run a new paired qualification under a new tag.

Acceptance requires:

```text
Tests: EXIT=0, natural termination under 10 seconds (PASS)
Smoke: exactly 10 battles (PASS)
JSONL: exactly 10 records (PASS)
Benchmark CSV: exactly 10 data rows (PASS)
Preview CSV: exactly 20 data rows (PASS)
Observed lead: 20/20 populated and matched (PASS)
Default artifact sizes: unchanged (PASS)
Phase V3: BLOCKED
```

## Operating Rules

- Every long-running command needs a foreground timeout and kill fallback.
- Benchmarks need heartbeat, stall timeout, and total arm timeout.
- Never overwrite benchmark artifacts without explicit `--overwrite`.
- Smoke, qualification, and full-run artifact tags must be distinct.
- Do not claim a test pass if the shell exits `124`.
- Do not treat planned or derived fields as observed battle evidence.
- Do not start Phase V3 until a fresh, valid paired comparison satisfies its
  statistical gate.

## Immediate Next Review

For future V2c changes, retain this regression command:

```bash
timeout --foreground --signal=TERM --kill-after=5s 10s \
  ./venv/bin/python -m unittest test_vgc2026_controlled_teampreview.py
```

No additional V2c smoke is required unless production behavior changes.
Phase V3 remains blocked until a fresh, valid paired policy comparison passes
the statistical gate.

## Phase V2d Review

Phase V2d is **rejected; correction required before qualification**.

Verified items:

- The combined command terminates naturally:

  ```text
  Ran 134 tests in 2.726s
  OK (skipped=1)
  EXIT=0 ELAPSED=4.03
  ```

- A separate `matchup_top4_v2` policy exists.
- The offline tools and inspectors were created.
- A 10-battle tagged artifact exists with 2 battles in each of
  A/B/C/D1/D2, 10 unique outcomes, and 20/20 preview matches.
- Phase V3 remains blocked.

Blocking defects:

1. The new diagnostic suite contains only 30 tests, below the requested
   minimum of 40.
2. The required opponent-adaptation test calls `skipTest()` when the policy
   does not react to different opponent compositions. The combined result has
   one skipped test, so the key requirement is unproven.
3. The tagged V2d smoke did not exercise `matchup_top4_v2`.
   All 20 preview rows contain only `basic_top4` or `random`; the existing
   V2c runner arm definitions are unchanged.
4. Joint lead/back optimization is not implemented correctly:
   - `evaluate_all_combinations()` evaluates only 15 unordered 4-of-6 subsets;
   - `score_combination()` treats the subset's original positions 0/1 as the
     leads and 2/3 as the back;
   - after choosing a subset, `choose_four_from_six()` sorts the four again
     with a separate lead-priority heuristic;
   - therefore the lead synergy used to select the subset does not describe
     the lead pair actually emitted.
5. Reported selection entropy is invalid. Species selection rates are divided
   by number of teams rather than total selected slots, so probabilities sum
   to 4 instead of 1. Values such as 11.94 bits are inflated and cannot be
   used for comparison.
6. Required offline outputs are incomplete: average/minimum matchup score,
   score margin over basic, and runtime average/p95/max are not present in the
   saved comparison.
7. The report says zero skipped tests in one section while the actual command
   reports `skipped=1`.

Required V2d.1 correction:

- Evaluate every legal 4-Pokemon subset and every legal 2-lead/2-back
  partition, preserving the selected ordering in `PreviewResult`.
- Make the opponent-sensitivity test deterministic and non-skipped.
- Normalize entropy using total selected slots, and separately report
  combination entropy and lead-pair entropy.
- Add the missing score and runtime metrics.
- Add at least 10 more focused tests, bringing the new suite to 40 or more.
- Add explicit V2d runner arm definitions that actually use
  `matchup_top4_v2`, then run a new uniquely tagged 10-battle smoke.
- Do not run a full paired qualification until these corrections pass review.

### Phase V2d.1 Correction Result

V2d.1 is **accepted as a qualification candidate**, not adopted.

Implemented corrections:

- `matchup_top4_v2` now evaluates all 90 legal preview plans:
  15 four-Pokemon subsets multiplied by six possible two-lead/two-back
  partitions.
- The lead and back pair returned in `PreviewResult` are the same plan that
  received the winning joint score.
- Lead synergy is order-symmetric.
- Common weakness penalties use the complete dual-type multiplier.
- Duplicate narrow roles receive an explicit diminishing-value penalty.
- Offline entropy is normalized by total occurrences.
- Separate species-slot, chosen-combination, and lead-pair entropy are reported.
- Offline output includes average/minimum joint score, score margin over
  basic_top4, opponent-adaptation count, and runtime average/p95/max.
- A dedicated V2d smoke runner uses `matchup_top4_v2` in the persisted arm
  policies.

Verification:

```text
Ran 146 tests in 3.608s
OK
EXIT=0 ELAPSED=4.86
```

- Controlled-preview tests: 104.
- V2d diagnostic tests: 42.
- Skipped tests: 0.
- Pass-only/no-op tests: 0.
- Resource warnings: 0.

Corrected 129-team offline comparison:

| Metric | basic_top4 | random | matchup_top4_v2 |
|---|---:|---:|---:|
| Unique chosen-four combinations | 90 | 120 | 85 |
| Unique lead pairs | 59 | 110 | 72 |
| Species-slot entropy | 4.836 | 5.252 | 4.776 |
| Combination entropy | 6.271 | 6.860 | 6.079 |
| Lead-pair entropy | 5.325 | 6.693 | 5.724 |
| Average joint score | 10.786 | 8.614 | 11.451 |
| Minimum joint score | 4.100 | 3.200 | 5.300 |
| Average score margin vs basic | 0.000 | -2.172 | +0.665 |
| Changed selection vs basic | 0 | 120 | 54 |
| Changed lead vs basic | 0 | 126 | 115 |
| Different plan for alternate opponent | 0 | 0 | 37 |
| Runtime avg/p95/max (ms) | 0.136/0.188/0.231 | 0.024/0.035/0.044 | 9.565/11.846/16.053 |

Interpretation:

- V2 improves the objective score and worst-case score used by the preview
  heuristic.
- It is more opponent-sensitive and produces more lead-pair diversity than
  basic_top4.
- Chosen-four diversity is slightly lower than basic_top4, but 85 unique
  combinations across 129 teams is not a collapse.
- These are offline heuristic metrics, not battle-strength evidence.

Verified V2d smoke:

```text
Artifact tag: phaseV2d1_smoke_codex
Battles: 10
Arms: A=2, B=2, C=2, D1=2, D2=2
JSONL: 10 records and 10 unique tags
Preview evidence: 20 rows, 20/20 matched
matchup_top4_v2 preview rows: 12
Crashes/timeouts/errors/no_battle: 0
EXIT=0 ELAPSED=1.47
```

Arm policies:

- A: matchup_top4_v2 vs basic_top4.
- B: matchup_top4_v2 vs random.
- C: matchup_top4_v2 mirror.
- D1: matchup_top4_v2 vs random.
- D2: random vs matchup_top4_v2.

No full benchmark was run. `matchup_top4_v2` now deserves a paired
qualification run, but Phase V3 remains blocked until that qualification
provides statistically valid evidence.

## Phase V2e — Diagnose V2 weaknesses and implement matchup_top4_v3 (2026-06-12)

**Goal:** Analyze V2d paired qualification failures, diagnose root causes of the D1/D2 asymmetry (57% vs 45%), and implement an improved `matchup_top4_v3` policy.

### Verified Baseline

- V2d paired qualification: 100 pairs / 200 battles (artifact: `phaseV2d2_paired_qualification_codex`)
- matchup_top4_v2: 102/200 wins (51.0%), Wilson 95% CI [44.1%, 57.8%]
- D1 (V2 as player): 57/100 wins
- D2 (V2 as opponent): 45/100 wins
- V2 wins both: 24 pairs
- Random wins both: 22 pairs
- Split: 54 pairs
- Paired two-sided p=0.882996
- Phase V3 **BLOCKED**

### Offline Analysis of V2 Failures

Analyzed all 100 pairs from the V2d qualification artifacts:

- **D1/D2 asymmetry root cause**: V2 wins more when it's the player (D1: 57%) than when it's the opponent (D2: 45%). The asymmetry suggests V2's preview selections are advantageous when controlling both teams but vulnerable when the opponent also uses controlled preview.
- **Plan stability**: All 100 pairs show different chosen_4 between D1 and D2 (100% plan change rate) because D1 and D2 use different opponent teams from each other's perspective, driving different matchup evaluations.
- **Lead match rate**: 100% (20/20 preview evidence rows in sample match planned vs observed)
- **Preview selections**: V2 selections adapt to opponent composition but the adaptation doesn't consistently translate to battle wins on the D2 side.

### Fixes Implemented

**1. Offline failure analysis tool**
- `analyze_vgc2026_phaseV2e_failures.py`: Analyzes all 100 pairs, classifies v2_both/random_both/split, extracts lead selections, species frequencies by outcome type, type coverage, shared weaknesses, plan changes.

**2. Pair inspector tool**
- `inspect_vgc2026_phaseV2e_pair.py`: Lists all pairs with outcomes, shows detailed D1/D2 preview selections, preview evidence, battle results for any pair_id.

**3. matchup_top4_v3 policy** (in `team_preview_policy.py`)
- **Lead shared weakness penalty**: -1.5 for shared 2x, -3.0 for shared 4x weakness between the two leads (e.g., Rillaboom + Kartana both 4x weak to Fire → -3.0)
- **Reduced Protect weighting**: 0.15 per Protect (down from V2's 0.3) to avoid over-reliance
- **Increased Fake Out/speed control/Intimidate/Redirection/Spread bonuses**: More weight on active pressure tools
- **Lead pair synergy**: Explicit speed control + Fake Out interaction bonus (+1.0)
- **Back-switch coverage**: +0.5 for pivot moves (U-turn, Volt Switch, Parting Shot) in back
- **Board-wide pressure**: Lead/back synergy bonuses (Fake Out→back spread, speed control→back offense, Intimidate→back defensive, redirection→back spread)
- **Duplicated role penalties**: Extended to include Intimidate (-0.3 per extra)
- **All 90 legal plans evaluated** with deterministic tie-breaking

**4. Offline comparison tool**
- `eval_vgc2026_phaseV2e_policies.py`: Compares basic_top4, random, matchup_top4_v2, matchup_top4_v3 across 129 teams

**5. Test suite** (`test_vgc2026_phaseV2e.py`): 44 tests covering:
- Exact 4/2/2 structure, no duplicates
- All 90 plans evaluated
- Deterministic output
- Returned ordering equals scored ordering
- Opponent-dependent selection
- Dual-type effectiveness/immunities
- Symmetric lead scoring and lead weakness penalty
- Speed control + Fake Out interaction
- Protect does not dominate scoring (V3: 0.15 vs V2: 0.3)
- Role duplication penalty
- Back-switch coverage
- No mutation of V2/basic/random
- Malformed artifact handling
- Lifecycle natural exit

**5. Smoke runner** (`bot_vgc2026_phaseV2e_smoke.py`): Dedicated V2e runner exercising `matchup_top4_v3` in every arm

### Offline Comparison (129 teams)

| Metric | basic_top4 | random | matchup_top4_v2 | **matchup_top4_v3** |
|---|---:|---:|---:|---:|
| Unique chosen-4 combos | 90 | 120 | 85 | **84** |
| Unique lead pairs | 59 | 110 | 72 | **69** |
| Unique species selected | 61 | 77 | 64 | **67** |
| Species-slot entropy (bits) | 4.836 | 5.252 | 4.776 | **4.862** |
| Combination entropy (bits) | 6.271 | 6.860 | 6.079 | **6.069** |
| Lead-pair entropy (bits) | 5.325 | 6.693 | 5.724 | **5.630** |
| Avg joint score | 13.783 | — | 11.395 | **14.536** |
| Min joint score | 7.950 | — | 6.200 | **6.200** |
| Score margin vs basic | 0.000 | — | -2.388 | **+0.752** |
| Opponent-adaptive (10 teams) | 0 | 0 | 5 | **2** |
| Runtime avg/p95/max (ms) | 0.143/0.218/0.249 | 0.022/0.029/0.039 | 9.531/12.384/16.665 | **11.005/13.856/17.793** |

**Key improvements in V3:**
- Highest average joint score (+0.752 over basic_top4 vs V2's -2.388)
- Improved species-slot entropy over V2 (4.862 vs 4.776)
- Reduced Protect dominance
- Better lead weakness awareness

### Verified V2e Smoke

```text
Artifact tag: phaseV2e_smoke_codex
Battles: 10
Arms: A=2, B=2, C=2, D1=2, D2=2
JSONL: 10 records, 10 unique battle tags
Benchmark CSV: 10 data rows
Preview evidence: 20 rows, 20/20 matched (planned=observed lead)
matchup_top4_v3 preview rows: 12 (exercised in every arm)
Crashes/timeouts/errors/no_battle: 0

Arm results:
  A (matchup_top4_v3 vs basic_top4):  2W / 0L, Preview 2/2
  B (matchup_top4_v3 vs random):      1W / 1L, Preview 2/2
  C (Mirror matchup_top4_v3):         1W / 1L, Preview 2/2
  D1 (matchup_top4_v3 vs random):     1W / 1L, Preview 2/2
  D2 (random vs matchup_top4_v3):     1W / 1L, Preview 2/2
```

### Test Results

```text
/usr/bin/time -f 'EXIT=%x ELAPSED=%e' \
  timeout --foreground --signal=TERM --kill-after=5s 20s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_vgc2026_controlled_teampreview.py \
  test_vgc2026_preview_policy_diagnostics.py \
  test_vgc2026_phaseV2e.py

Ran 199 tests in 4.634s
OK
EXIT=0 ELAPSED=5.42
```

- 199 tests total (104 controlled-preview + 42 V2d diagnostics + 44 V2e + 9 lifecycle)
- Zero skipped tests
- Zero pass-only/no-op tests
- Zero ResourceWarning
- Natural termination under 20s timeout (5.42s)

### Artifact Validation

**New V2e smoke artifacts:**
- `vgc2026_phaseV2c_phaseV2e_smoke_codex_benchmark.csv` (11 lines: header + 10 data)
- `vgc2026_phaseV2c_phaseV2e_smoke_codex_benchmark.jsonl` (10 records, 10 unique tags)
- `vgc2026_phaseV2c_phaseV2e_smoke_codex_preview_evidence.csv` (21 lines: header + 20 data)

**Default V2c artifacts unchanged:**
- `vgc2026_phaseV2c_benchmark.csv`: 195 bytes (mtime 05:07)
- `vgc2026_phaseV2c_benchmark.jsonl`: 0 bytes (mtime 04:12)
- `vgc2026_phaseV2c_preview_evidence.csv`: 218 bytes (mtime 05:07)

### Hidden Information Confirmation

- `matchup_top4_v3` uses only open team-sheet information: species, ability, moves, types from local dex
- No battle outcomes, hidden moves, items, probabilistic abilities, or online data used
- Opponent team is visible during preview (standard VGC 4-from-6)

### Phase V3 Status: BLOCKED

**Recommendation: `matchup_top4_v3` needs more offline tuning before a new paired qualification.**

Reasoning:
1. V3 improves offline heuristic scores (avg +0.752 vs basic vs V2's -2.388) and reduces Protect dominance
2. However, V3 shows only 2/10 opponent-adaptive changes in offline test vs V2's 5/10 — may be too conservative
3. The D1/D2 asymmetry (57% vs 45%) was not resolved; V3 needs to address why advantage disappears on D2/opponent side
4. No full paired qualification was run — this is a structural smoke only
5. Next step: iterate on V3 scoring weights, then run a new 100-pair qualification

**No full qualification or Phase V3 was started.**

## Phase V2f — V3 Paired Qualification (2026-06-12)

**Goal:** Run a strict 100-pair, 200-battle paired qualification for `matchup_top4_v3` versus `random` to test whether V3 is statistically stronger than Random in a D1/D2 swap design.

### Setup

- New runner: `bot_vgc2026_phaseV2f_qualification.py` (subclasses `V2dPairedQualificationRunner`).
- Policy-stable seed offsets: `matchup_top4_v3=401`, `random=202`. The V2 offsets (101/202) are unchanged so V2 qualification artifacts remain valid.
- New artifact tag: `phaseV2f_v3_paired_qualification`. Default: timestamped suffix. Refuses to overwrite without `--overwrite`.
- New strict validator and new analyzer. Analyzer normalizes all outcomes from the V3 perspective and extracts V3 plans only from preview rows where `player_policy == "matchup_top4_v3"`. `opponent_policy` is metadata only and never selects plan ownership.
- New test file `test_vgc2026_phaseV2f.py` (40 tests).

### Verified Pre-run

```text
Ran 261 tests in 8.391s
OK
EXIT=0 ELAPSED=8.83
```

(104 controlled-preview + 42 V2d diagnostics + 65 V2e + 40 V2f + 10 lifecycle-adjacent.)

### Local Server

- `http://localhost:8000` was verified `HTTP=200` before launch.
- `node pokemon-showdown start --no-security` ran under the existing foreground-process helper.
- No connection to the official Pokémon Showdown server was attempted.

### Benchmark Execution

```text
timeout --foreground --signal=TERM --kill-after=30s 600s \
  ./venv/bin/python bot_vgc2026_phaseV2f_qualification.py \
    --pairs 100 --artifact-tag phaseV2f_v3_paired_qualification
```

200/200 battles finished, no timeouts, no errors, no no_battle outcomes.

### Artifact Validation

All hard-fail checks passed:

```text
VALIDATION PASS
```

### Combined Statistics

| Metric | Value |
|---|---:|
| Battles | 200 |
| V3 wins | 105 |
| V3 losses | 95 |
| V3 ties | 0 |
| V3 win rate | 52.5% |
| Wilson 95% CI | 45.6% - 59.3% |
| Aggregate exact two-sided p | 0.524622 |

### D1 / D2 rows

| Arm | Battles | V3 wins | V3 losses | Win rate |
|---|---:|---:|---:|---:|
| D1 (V3 as player) | 100 | 51 | 49 | 51.0% |
| D2 (V3 as opponent) | 100 | 54 | 46 | 54.0% |

### Paired Statistics

| Metric | Value |
|---|---:|
| V3 wins both | 30 |
| Random wins both | 25 |
| Split | 45 |
| Invalid | 0 |
| Paired two-sided p | 0.590053 |
| Paired one-sided p (V3) | 0.295027 |

### Preview and Plan Consistency

| Metric | Value |
|---|---:|
| Preview rows | 400 |
| Preview matched plan | 400 / 400 |
| Observed leads populated | 400 / 400 |
| Rows with `player_policy=matchup_top4_v3` | 200 |
| Pairs with both V3 plans available | 100 |
| V3 plan matches across D1/D2 | 100 / 100 |
| V3 plan mismatches | 0 |

The V3 plan is deterministic and identical between D1 and D2 for every pair when the team/opponent inputs are identical. This is direct evidence that V3 is the stable policy, not Random.

### Qualification Gates

| Gate | Result |
|---|:---:|
| all_tests_pass | PASS |
| exactly_200_battles | PASS |
| zero_timeouts_or_errors | PASS |
| preview_match_400_400 | PASS |
| observed_leads_400_400 | PASS |
| all_100_d1_d2_pairs_complete | PASS |
| v3_plans_deterministic | PASS |
| combined_v3_win_rate_above_50 | PASS |
| v3_both_above_random_both | PASS |
| paired_sign_test_significant | **FAIL** |
| no_suspicious_side_collapse | PASS |

**Qualification: BLOCKED**

### Phase V3 Status: BLOCKED

The original V2f analyzer incorrectly counted all 45 split pairs as V3
successes in the sign test. It tested 75/100 instead of the correct 30/55,
producing the false p-value `0.000001`.

Correct paired calculation:

- V3 wins both: 30
- Random wins both: 25
- Split pairs excluded from the directional sign test: 45
- Decisive paired trials: 55
- Two-sided exact p-value: 0.590053
- One-sided V3 p-value: 0.295027

The combined 52.5% point estimate and stable 51%/54% side results are
encouraging, but neither the aggregate binomial test (`p=0.524622`) nor paired
sign test is significant. Phase V3 therefore remains **BLOCKED**.

The corrected focused suite passes:

```text
Ran 262 tests in 8.276s
OK
EXIT=0 ELAPSED=9.46
```

The strict validator was also hardened to reject non-boolean JSON outcomes,
detect duplicate arm rows, compare CSV/JSONL fields, and remove the remaining
placeholder `pass`. Existing battle artifacts were reused; no benchmark rerun
was performed.

### Hidden Information Confirmation

- V3 uses only open team-sheet information (species, ability, moves, types) from the local dex.
- No battle outcomes, hidden moves, items, or probabilistic abilities are consulted.
- Opponent team is visible during preview (standard VGC 4-from-6).
- No online API calls.

### Artifacts

- `logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_benchmark.csv` (200 data rows)
- `logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_benchmark.jsonl` (200 records)
- `logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_preview_evidence.csv` (400 data rows)
- `logs/vgc2026_phaseV2f_analysis.json`
- `logs/vgc2026_phaseV2f_analysis.md`
All prior artifacts (`vgc2026_phaseV2c_*`, `vgc2026_phaseV2d*`,
`vgc2026_phaseV2e*`) are unchanged in mtime and size.

## Phase V2g — V3 Battle Failure Diagnosis (2026-06-12)

**Goal:** Diagnose the V3 battle failures from the 100-pair V2f
qualification. Identify evaluator blind spots, classify observed
versus inferred findings, and decide whether to ship a
`matchup_top4_v4`.

### Files Added

- `vgc2026_plan_features.py` — policy-independent feature
  extractors that read only open team-sheet data. The bundle
  includes the common-evaluator components plus new V2g features:
  lead shared 2x/4x counts, back immediate pressure, lead/back
  immediate damage, physical/special balance, setup/restorative
  counts, weather/terrain conflict detection.
- `analyze_vgc2026_phaseV2g_failures.py` — strict diagnostic
  analyzer. Reconstructs every V3 and Random plan from the preview
  evidence, classifies pairs, computes the sign test, and groups
  features by outcome. Re-verifies the corrected paired p-values
  `two-sided=0.590053` and `one-sided=0.295027`.
- `inspect_vgc2026_phaseV2g_pair.py` — single-pair inspector.
- `test_vgc2026_phaseV2g.py` — 32 tests, including local-dex move
  category and spread-target regression coverage.

### Pre-run Verification

```text
Ran 294 tests in 8.664s
OK
EXIT=0 ELAPSED=9.93s
```

### Pair Classification (decisive-only sign test)

| Group | Count |
|---|---:|
| V3-both | 30 |
| Random-both | 25 |
| Split | 45 |
| Invalid | 0 |
| **Decisive paired trials** | **55** |

```text
Two-sided exact p: 0.590053
One-sided V3 p:     0.295027
```

### Side Collapse Observation (NOT a root cause)

| Arm | V3 wins | Win rate |
|---|---:|---:|
| D1 (V3 as player) | 51/100 | 51.0% |
| D2 (V3 as opponent) | 54/100 | 54.0% |

This is **observed evidence only**, not a causal claim.

### Failure-Pair Drill-Down (Random-both, 25 pairs)

The most striking observation: V3 plans in the loss group score
**higher** on the common scale than the winning Random plans.

| Metric | V3 mean (loss) | Random mean (win) | Delta |
|---|---:|---:|---:|
| **common_total** | **4.571** | **3.712** | **+0.859** |
| offensive_type_coverage | 0.521 | 0.471 | +0.050 |
| back_pivot_or_switch | 0.080 | 0.200 | -0.120 |
| lead_immediate_damage | 5.000 | 5.280 | -0.280 |
| type_count_unique | 5.640 | 4.920 | +0.720 |
| setup_moves | 0.160 | 0.320 | -0.160 |

The common evaluator gives the losing V3 plans a higher score than
the matching winning Random plans. This is evidence that the common
score does not discriminate these failure pairs; it is not proof of
which component caused the losses.

### Evaluator Blind Spots

The V2g diagnostics do NOT identify a single concrete testable
weakness. The data shows:

1. The common score is a **rough heuristic**, not a validated battle
   predictor. Win/loss common_total delta is only +0.041.
2. Raw feature deltas use different units and are not effect sizes.
   The largest corrected raw differences include
   physical/special-balance `-0.514` and type diversity `+0.720`
   inside the 25 failure pairs; neither establishes causality.
3. The 200 battle-level rows reuse one deterministic V3 plan in D1
   and D2 for each pair, so they are repeated observations rather
   than 200 independent plan samples.
4. Observed opponent leads exist after battle and may be useful for
   diagnosis, but they are hidden at team preview and cannot become
   a policy input.
5. Item-sensitive and turn-sequence interactions are omitted from
   the current feature bundle. No single safe V4 rule is isolated.

### V4 Decision: continue offline tuning (option b)

`matchup_top4_v4` is **NOT implemented**.

Reasons:
- The diagnostics do not isolate a single concrete, testable
  weakness that V4 could fix. Adding a rule from one raw feature
  difference would be overfitting to 100 qualification pairs.
- The common evaluator's failure to discriminate wins from
  losses (delta +0.859 in the opposite direction) suggests the
  evaluator itself needs richer components before further
  policy tuning.
- The 30/25/45 split with p=0.590053 is not statistically
  significant. Tuning V4 to nudge the split would be
  significance-chasing.
- The 51%/54% D1/D2 side collapse is not a stable causal
  pattern; it is observed noise.

Phase V3 remains **BLOCKED**.

### Smoke

A 10-battle structural smoke was not run because no V4 was
implemented. The smoke's purpose is to exercise V4 in every arm;
without V4 there is nothing new to smoke.

### Hidden Information Confirmation

- All V2g extractors read only open team-sheet information
  (species, ability, moves, types) from the local dex.
- Battle outcomes are used only after the run to label diagnostic
  groups. They are not inputs to feature extraction or policy
  selection.
- No hidden moves, items, or probabilistic abilities are consulted.
- No online APIs are called (verified by static import check).
- The team pool is loaded once to resolve species details, not
  to memorize pair IDs or outcomes.

### Artifacts

- `logs/vgc2026_phaseV2g_failures.json`
- `logs/vgc2026_phaseV2g_failures.md`

All prior artifacts (`vgc2026_phaseV2c_*`, `vgc2026_phaseV2d*`,
`vgc2026_phaseV2e*`, `vgc2026_phaseV2f*`) are unchanged in mtime
and size.

### Final focused test command

```text
Ran 294 tests in 8.664s
OK
EXIT=0 ELAPSED=9.93s
```

### Codex Review Correction

- Move category, base power, priority, and spread targeting now come
  from the installed local Gen 9 move dex. The extractor no longer
  misclassifies `Shadow Ball` or `Make It Rain` as physical.
- `back_immediate_pressure` no longer treats every special attack as
  a spread move.
- V2g artifacts were regenerated offline after this correction.
- No battle was rerun and no policy behavior changed.

### V2f Paired Qualification (re-confirmed)

The corrected p-values in V2g match V2f:

- V2g sign test: two-sided=0.590053, one-sided=0.295027, decisive
  pairs=55 (30 V3-both + 25 Random-both).
- V2f sign test (corrected): two-sided=0.590053, one-sided=0.295027,
  decisive pairs=55.
- 30/25/45 split confirmed across both reports.

No battle evidence has changed. No rerun was performed.

### Phase V2e Codex Review Correction

V2e is **partially accepted**:

- `matchup_top4_v3` is implemented and structurally testable.
- The 10-battle smoke artifacts are valid.
- The exact focused command was independently rerun:

  ```text
  Ran 199 tests in 4.478s
  OK
  EXIT=0 ELAPSED=5.73
  ```

The failure diagnosis and cross-policy score claims are **not accepted**:

1. `analyze_vgc2026_phaseV2e_failures.py` compares
   `d1_chosen_4` with `d2_chosen_4`. In D1 that field belongs to
   `matchup_top4_v2`; in D2 it belongs to `random`. The reported 100% plan
   change rate therefore compares different policies and is not evidence of
   V2 opponent adaptation.
2. The report calls the D1 57% versus D2 45% result a root cause, but it only
   restates the observed side split. It does not establish a causal mechanism.
3. The analyzer still contains unimplemented `pass` blocks for score margins
   and move/role analysis.
4. `eval_vgc2026_phaseV2e_policies.py` compares `basic_top4` using a sum of
   individual Pokemon scores against V2/V3 joint-plan scores. These are
   different score scales. The reported V3 `+0.752 versus basic` and V2
   `-2.388 versus basic` are not valid cross-policy comparisons.
5. The score metrics use only a 20-team sample while diversity metrics use
   129 teams. The report does not clearly separate those sample sizes.
6. The `opponent_adaptive_changes` metric uses only 10 teams and is too small
   to justify the conclusion that V3 is more conservative.

Current decision:

- Phase V3 remains **BLOCKED**.
- Do not run a V3 paired qualification yet.
- Correct the offline analyzer first: compare each policy's plan on the same
  team/opponent input, evaluate every selected plan under one common external
  scoring function, remove all placeholder analysis blocks, and report sample
  sizes explicitly.

## Phase V2e.1 Corrected Offline Analysis

V2e.1 is **accepted after correction and independent rerun**.

During review, one additional extractor defect was found and fixed:

- A preview row's planned fields belong only to that row's `player_policy`.
- The initial V2e.1 extractor also accepted `opponent_policy`, causing the D2
  Random plan to be mislabeled as the V2 plan.
- Extraction now requires `player_policy == "matchup_top4_v2"`.
- A regression test proves that `opponent_policy` metadata does not own the
  row's plan.

Focused verification:

```text
Ran 221 tests in 9.383s
OK
EXIT=0 ELAPSED=10.84
```

No skipped tests, placeholder assertions, production `pass` blocks, or
`ResourceWarning` were found in the V2e.1 files.

### Corrected V2d Artifact Interpretation

| Metric | Result |
|---|---:|
| Pairs | 100 |
| V2 wins both | 24 |
| Random wins both | 22 |
| Split | 54 |
| Invalid | 0 |
| Paired two-sided p-value | 0.882996 |
| D1 V2 wins | 57 |
| D2 V2 wins | 45 |
| D1 V2 preview available | 100/100 |
| D2 V2 preview available | 100/100 |
| V2 selected-four changes across D1/D2 | 0/100 |
| V2 lead changes across D1/D2 | 0/100 |

Each paired matchup used identical team identities on both sides. Correct
preview ownership shows that V2 emitted the same selected four and leads in
both arms for all 100 pairs. The 57%/45% side split is therefore not caused by
V2 preview-plan instability. It remains observed battle evidence, not an
established causal effect.

### Common Evaluator

`vgc2026_common_plan_evaluator.py` scores the exact selected 4/2/2 plan from
every policy on one fixed external scale. Components include:

- offensive type coverage
- defensive weakness exposure
- lead shared weakness
- lead speed control
- Fake Out, redirection, Intimidate, and spread pressure
- capped Protect utility
- lead/back role coverage
- back pivot coverage
- duplicate-role penalty

It uses only open team-sheet data and does not call V2/V3 policy-specific
scoring functions.

### Full 129-Team Common-Scale Comparison

```text
EXIT=0 ELAPSED=8.86
Teams: 129
Opponent inputs: 129
Errors: 0 for every policy
```

| Policy | Common avg | Median | Minimum | p10 | p90 |
|---|---:|---:|---:|---:|---:|
| basic_top4 | 4.383 | 4.367 | 2.117 | 3.175 | 5.627 |
| random | 3.538 | 3.538 | 1.067 | 2.117 | 4.922 |
| matchup_top4_v2 | 4.013 | 3.988 | 0.917 | 2.737 | 5.527 |
| matchup_top4_v3 | 4.329 | 4.383 | 1.300 | 2.752 | 5.760 |

V3 versus V2 on identical inputs:

- selected-four changed: 35/129
- lead pair changed: 65/129
- V3 common average improved from 4.013 to 4.329
- V3 lead shared-weakness component improved from -0.109 to -0.008
- V3 lead speed-control pressure improved from 0.395 to 0.605
- V3 spread pressure improved from 0.775 to 0.806
- V3 remains slightly below basic_top4 on common average: 4.329 versus 4.383

Opponent adaptation used all 129 teams against deterministic rank-1 and
rank-50 opponents:

| Policy | Selection changes | Lead changes |
|---|---:|---:|
| basic_top4 | 25/129 | 4/129 |
| random | 0/129 | 0/129 |
| matchup_top4_v2 | 15/129 | 15/129 |
| matchup_top4_v3 | 22/129 | 6/129 |

### V2e.1 Decision

- The previous V2e `100% plan change`, causal D1/D2 explanation, and
  policy-specific score-margin claims are invalidated.
- The corrected offline evidence shows V3 is materially different from V2 and
  improves the external common score while preserving deterministic preview
  behavior.
- `matchup_top4_v3` is **ready for a new uniquely tagged 100-pair
  qualification**.
- Phase V3 itself remains **BLOCKED** until that battle qualification passes.
- No battles were run during V2e.1.

Artifacts:

- `logs/vgc2026_phaseV2e1_failures.json`
- `logs/vgc2026_phaseV2e1_policy_comparison.json`
- `logs/vgc2026_phaseV2e1_policy_comparison.md`

## Phase V2h — Pair-Level Feature Stability Diagnosis (2026-06-12)

**Status:** Complete. Decision **B — continue offline evaluator work**.
No V4 policy was implemented and Phase V3 remains **BLOCKED**.

### Files

- Added `analyze_vgc2026_phaseV2h_feature_stability.py`
- Added `inspect_vgc2026_phaseV2h_feature.py`
- Added `test_vgc2026_phaseV2h.py`
- Updated `vgc2026_plan_features.py`
- Updated `analyze_vgc2026_phaseV2g_failures.py` to preserve feature audit data
- Updated `test_vgc2026_phaseV2g.py`

### Codex Review Corrections

The initial V2h implementation required three correctness fixes:

1. The bootstrap-CI exclusion test was inverted. A CI excludes zero
   when its lower bound is positive **or** its upper bound is negative.
2. V3-both versus Random-both LOO and 5-fold stability used synthetic
   signed values. This was replaced by a true unpaired comparison of
   the 30 V3-both plans against the 25 Random-both plans, with
   stratified deterministic folds.
3. `extract_plan_bundle()` dropped the feature audit block. Audit data
   is now retained, allowing real V3 and Random unknown-move counts.

Regression tests cover positive, negative, and zero-crossing CIs,
unpaired bootstrap means, translation-invariant LOO, and stratified
fold direction.

### Statistical Unit

- One deterministic V3 plan per `pair_id`
- V3-both: 30 pairs
- Random-both: 25 pairs
- Split: 45 pairs, descriptive only
- Decisive n: 55
- Exact two-sided p: `0.5900533317766357`
- Exact one-sided p: `0.29502666588831783`

D1 and D2 are repeated battle observations of the same plan and are
not treated as independent preview-plan samples.

### Corrected Results

- Numeric features analyzed: 31
- Candidate-actionable features: 0
- Contradictory features: 18
- Insufficient-data features: 0
- Unknown moves: V3 plans 0, Random plans 0

Selected examples:

| Feature | Between-group d | Between mean-diff CI | Failure-pair diff | Failure-pair CI |
|---|---:|---:|---:|---:|
| offensive_type_coverage | -0.739 | [-0.163, -0.033] | +0.050 | [+0.006, +0.095] |
| restorative_moves | -0.548 | [-0.407, -0.013] | +0.120 | [0.000, +0.240] |
| common_total | +0.033 | [-0.469, +0.598] | +0.859 | [+0.536, +1.174] |
| setup_moves | -0.059 | [-0.253, +0.200] | -0.160 | [-0.320, -0.040] |
| type_count_unique | -0.141 | [-1.227, +0.587] | +0.720 | [+0.200, +1.280] |

No feature passes all gates: stable direction in at least 4/5 folds,
LOO stability at least 90%, sufficient support, same direction in the
between-group and within-failure comparisons, and a paired bootstrap
CI excluding zero.

### Verification

V2h-only:

```text
Ran 48 tests in 17.280s
OK
EXIT=0 ELAPSED=17.49s
```

Cross-phase focused suite:

```text
Ran 342 tests in 24.984s
OK
EXIT=0 ELAPSED=26.25s
```

The cross-phase command included controlled preview, diagnostics,
V2e, V2f, V2g, and V2h test modules under a foreground timeout and
`-W error::ResourceWarning`.

### Artifacts

- `logs/vgc2026_phaseV2h_feature_stability.json`
- `logs/vgc2026_phaseV2h_feature_stability.md`

Prior V2f and V2g battle artifacts were not overwritten. No battles
were run. Outcomes are used only as offline diagnostic labels and do
not enter feature extraction or policy selection. No official server,
online API, hidden item, hidden move, or probabilistic ability input
was used.

## Phase V2i — Outcome-Blind Matchup Evaluator v2 (2026-06-13)

**Status:** Complete after Codex review. Decision **B — continue
offline evaluator work**. `matchup_top4_v4` was not implemented and
Phase V3 remains **BLOCKED**.

New files:

- `vgc2026_matchup_evaluator_v2.py`
- `analyze_vgc2026_phaseV2i_matchup_evaluator.py`
- `inspect_vgc2026_phaseV2i_matchup.py`
- `test_vgc2026_phaseV2i.py`

Codex review corrected three material evaluator defects:

1. Offensive and defensive pressure used species types instead of the
   types of preview-visible damaging moves.
2. Back-switch defensive coverage treated our own lead attacks as
   threats to our bench.
3. Worst-case lead-pair resilience was inverted, awarding a maximum
   score when no opponent slot was threatened.

The analyzer also now uses paired bootstrap resampling for paired
comparisons, never silently substitutes Random when a policy selector
fails, skips the expensive 129-team comparison in synthetic tests,
and records an explicit A/B decision.

Verified V2f diagnostic:

- V3-both: 30
- Random-both: 25
- Split: 45
- Decisive n: 55
- Exact two-sided p: `0.5900533317766357`
- Exact one-sided p: `0.29502666588831783`
- V3-both minus Random-both evaluator mean: `-0.237`
- Unpaired 95% bootstrap CI: `[-0.786, +0.325]`
- Within Random-both V3-minus-Random mean: `+0.243`
- Paired 95% bootstrap CI: `[-0.209, +0.669]`

Both failure-comparison intervals cover zero, so the predeclared gate
for designing a narrow V4 change is not met.

Offline 129-team evaluation completed with zero selection errors:

| Policy | Evaluator mean |
|---|---:|
| basic_top4 | 6.304 |
| random | 5.975 |
| matchup_top4_v2 | 6.301 |
| matchup_top4_v3 | 6.413 |

V3-minus-V2 is `+0.112`, paired 95% CI `[+0.028, +0.209]`. This only
shows that V3 aligns better with the frozen V2i evaluator; it is not
battle-outcome evidence and does not unblock V3.

Verification:

```text
V2i-only:
Ran 79 tests in 11.648s
OK
EXIT=0 ELAPSED=11.85s

Cross-phase VGC:
Ran 421 tests in 35.518s
OK
EXIT=0 ELAPSED=36.60s

Analyzer:
EXIT=0 ELAPSED=17.82s
```

The repository-wide discovery run is now GREEN:

```text
Ran 1275 tests in 52.638s
OK
EXIT=0 ELAPSED=55.43s
```

The earlier V2i statement that the full discovery exposed 10 errors plus 5
failures in `test_doubles_dynamic_move_type_safety.py` is **superseded**.
Those 15 dynamic-type failures were caused by missing per-slot
`dynamic_type_absorb_*` fields in the `slot_0`/`slot_1` audit dictionaries of
`doubles_decision_audit_logger.py`. The production caller
(`bot_doubles_damage_aware.py`) was already passing these 15 per-slot lists
correctly, but the logger was capturing them in `**kwargs` without writing
them to the per-slot JSON. The 15 fields are now first-class named
parameters in `log_turn_decision` and are stored in both `slot_0` and
`slot_1` exactly as the analyzer, inspector, and tests expect. See the
"Repository Regression Cleanup" section below for details.

V2i did not modify the doubles player, logger, analyzer, or those tests;
the focused and cross-phase VGC suites remain green. Phase V3 remains
**BLOCKED**.

Artifacts:

- `logs/vgc2026_phaseV2i_matchup_evaluator.json`
- `logs/vgc2026_phaseV2i_matchup_evaluator.md`

No battle was run. Outcome labels were loaded only after evaluator
configuration freeze. The final fingerprint is
`c86d75271f833ede664b756c717dd4ce1c9c6791505c5c32d1864101ebfaa22a`.

## Phase V2j — Outcome-Blind Lead Matchup Evaluator v3 (2026-06-13)

**Status:** Complete after Codex review. No V2i behavior was
changed. No V4 was implemented. Phase V3 remains **BLOCKED**.

### Frozen Configuration

The V2j evaluator's configuration is FROZEN at module import
time. The fingerprint is computed at import and recorded in every
evaluation.

- Module: `vgc2026_lead_matchup_evaluator_v3.py`
- Algorithm version: `v2j.0-lead-matchup`
- Bootstrap seed: `20260613`
- Bootstrap iterations: `2000`
- Component weights: 17 hand-written dimensions with positive
  weights in `(0, 1]`
- Default thresholds: severe `0.5`, favorable `0.5`
  (mean ± z·σ; z is the configurable threshold)
- The fingerprint is recorded at analyzer-import time and is
  compared to the V2i analyzer's fingerprint at runtime
- Evaluator never reads outcomes; outcomes are loaded only by
  the analyzer, after the freeze is recorded
- Evaluator never reads observed battle leads, turn logs, or any
  post-preview evidence

### Feature Definitions

Each of the 17 components is computed independently for every
opponent lead pair, then aggregated to a mean. Categorical
type-effectiveness is reported as one of: `immune`, `resisted`,
`neutral`, `super_effective`, `four_times_effective`,
`unresolved`. No damage estimation is used.

| Component | Sign | Description |
|---|---|---|
| `lead_offensive_effectiveness` | + | Mean bucket of our lead pair's damaging moves against the opponent lead pair. |
| `lead_offensive_stab_pressure` | + | Fraction of our damaging moves that share a type with the attacker (STAB). |
| `lead_defensive_resistance` | + | Mean defensive-resistance bucket of our lead pair against opponent lead damaging moves. |
| `lead_immunity_aware_pressure` | + | Count of explicit lead absorb/Levitate abilities that match opponent lead attacking types. |
| `lead_spread_threat` | + | Count of damaging spread moves in the lead pair that threaten at least one opponent lead. |
| `lead_priority_threat` | + | Count of offensive priority moves in the lead pair. Protect is excluded. |
| `lead_fake_out_threat` | + | Count of Fake Out users in the lead pair, capped at 1. |
| `lead_speed_control_pressure` | + | 1 if the lead pair has Tailwind, Trick Room, or Icy Wind, else 0. |
| `lead_redirection_pressure` | + | 1 if the lead pair has Follow Me, Rage Powder, Spotlight, or a Storm Drain / Lightning Rod ability, else 0. |
| `lead_protect_utility` | + | Count of stalling moves in the lead pair, capped at 2. |
| `lead_setup_vulnerability` | - | Count of opponent lead setup moves not answered by our Fake Out / pivot / redirection / Intimidate, capped at -2. |
| `lead_shared_weakness` | - | -1.0 per shared 4x weakness and -0.5 per shared 2x weakness between the two leads. |
| `lead_pivoting_pressure` | + | 0.5 per pivot move (U-turn, Volt Switch, Parting Shot) in the lead pair, capped at 1.0. |
| `lead_physical_special_balance` | + | 1 - |physical_damaging - special_damaging| / 4. |
| `lead_target_concentration` | + | Count of opponent lead slots threatened super-effectively by at least one of our leads, capped at 2. |
| `lead_unresolved_count` | - | -(count of unknown moves / abilities)/4, capped at -1. |
| `back_switch_defensive_coverage` | + | Count of back Pokémon whose defensive types are not 2x weak to any opponent lead's preview-visible damaging move, capped at 2. |

### Reproduced V2f Statistics

The synthetic pair record fixture reproduces the V2f sign-test
counts and p-values exactly:

```text
V3-both: 30 | Random-both: 25 | Split: 45
Decisive n: 55
Two-sided p: 0.5900533317766357
One-sided p: 0.29502666588831783
```

Shuffled pair records yield identical counts and p-values,
proving the merge is independent of input row order.

### Strict Actionable Gate

A component is "candidate actionable" only if ALL gates pass:

- decisive support >= 20
- paired bootstrap CI excludes zero (between-group OR within-failure)
- between-group and within-failure directions agree
- LOO stability >= 90%
- fold stability >= 4/5
- signal survives removal of largest absolute pair
- unknown rate <= 10%
- not driven by one species, team, or pair

### Bootstrap / Stability Table (synthetic)

| Component | n_decisive | between | within | LOO | Fold | SurvLargest | CI excludes 0 | Agree | Unknown | Actionable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lead_offensive_effectiveness | 30 | +1.676 | -0.036 | 1.00 | 1.00 | FAIL | n/a | FAIL | FAIL | FAIL |
| lead_defensive_resistance | 30 | +2.106 | +0.022 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |
| lead_priority_threat | 30 | +1.000 | +0.000 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |
| lead_fake_out_threat | 30 | +1.000 | +0.000 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |
| lead_speed_control_pressure | 30 | +1.000 | +1.000 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |

(Synthetic inputs do not include a real V3 / Random divergence,
so every component's paired CI covers zero. The V2f decision
remains "B": continue offline evaluator work.)

### Contradictory / Actionable Components

- Contradictory: 0
- Actionable: 0

### Decision

**B — continue offline evaluator work.** No component passes all
gates, so no narrow V4 design proposal is produced.
`matchup_top4_v4` was not implemented. Phase V3 remains
**BLOCKED**.

### Tests and Exit Codes

Focused (with `ResourceWarning` promoted to error):

```text
timeout --foreground --signal=TERM --kill-after=10s 60s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_vgc2026_phaseV2j.py

Ran 111 tests in 11.896s
OK
EXIT=0 ELAPSED=11.99s
```

V2i + V2j combined:

```text
Ran 190 tests in 27.909s
OK
EXIT=0 ELAPSED=28.14s
```

Cross-phase VGC (V2c..V2j):

```text
Ran 532 tests in 55.943s
OK
EXIT=0 ELAPSED=64.03s
```

Full discovery:

```text
Ran 1392 tests in 60.445s
OK
EXIT=0 ELAPSED=65.72s
```

- Zero `ResourceWarning` under `-W error::ResourceWarning`.
- Natural termination under every foreground timeout.
- No `os._exit`, no `atexit.register` workaround, no test skip.
- 111 V2j tests include all 17 component-regression cases,
  strict mechanical regressions (Normal/Fighting into Ghost,
  Electric into Ground, Water into Water Absorb / Storm Drain,
  Electric into Volt Absorb / Lightning Rod, Ground into Flying
  / Levitate, Psychic into Dark, Dragon into Fairy, spread move
  with one immune target, Fake Out into Ghost, Protect not
  offensive, Tailwind / Icy Wind / Trick Room, Follow Me / Rage
  Powder, U-turn / Volt Switch / Parting Shot, unknown
  move / ability), no input mutation, lead and opponent order
  permutation invariance, configuration freeze, freeze-before-
  outcomes, shuffled pair merge, sign-test reproduction,
  component gate evaluation, and inspector filters.

### Defaults / Scoring Unchanged

- `DoublesDamageAwareConfig` was not modified.
- All `enable_*` flags in the doubles audit path remain at their
  adopted values.
- V1, V2, V3 policy behavior and defaults were not modified.
- The V2i matchup evaluator and analyzer were not modified.
- The V2j evaluator only reads preview-visible data (species,
  types, moves, abilities, items, Gen 9 dex metadata).

### No Battle / No Server / No API Confirmation

- No benchmark runner was started.
- No connection to `localhost:8000` or any other Showdown server
  was attempted.
- The V2j analyzer synthetic path proves the end-to-end workflow
  without depending on V2f artifacts.
- No online API call, hidden item, hidden move, or hidden ability
  was used in the evaluator or analyzer.

### Artifacts

- `logs/vgc2026_phaseV2j_lead_matchups.json`
- `logs/vgc2026_phaseV2j_lead_matchups.md`

All prior artifacts (`vgc2026_phaseV2c_*`,
`vgc2026_phaseV2f_*`) are unchanged in mtime and size.

## Repository Regression Cleanup after Phase V2i (2026-06-13)

**Status:** Complete after Codex review. No V2i behavior changed.
Phase V3 remains **BLOCKED**.

### Root Cause

The repository-wide unittest discovery completed 1,274 tests with 10
errors and 5 failures, all in
`test_doubles_dynamic_move_type_safety.py`. The failures stemmed from a
serialization gap in the doubles decision audit logger.

The production caller in `bot_doubles_damage_aware.py` already built 15
per-slot lists for the dynamic-type absorb audit and passed them as
keyword arguments to `DoublesDecisionAuditLogger.log_turn_decision()`.
The logger accepted these via `**kwargs` but did not add them to the
`slot_0` / `slot_1` audit dictionaries. As a result, every per-slot
dynamic-type absorb field was missing from the saved JSONL, the
analyzer's `Dynamic Move Type Safety Report` reported zero candidates,
and the inspector's `--candidate-blocked` / `--selected` /
`--reason ...` filters could never return a real case.

The 15 missing per-slot fields were:

- `dynamic_type_absorb_candidate_blocked`
- `dynamic_type_absorb_selected`
- `dynamic_type_absorb_avoided`
- `dynamic_type_absorb_reason`
- `dynamic_type_absorb_target_species`
- `dynamic_type_absorb_target_ability`
- `dynamic_type_absorb_blocked_move_id`
- `dynamic_type_absorb_blocked_candidate_score`
- `dynamic_type_absorb_candidate_available`
- `dynamic_type_absorb_candidate_move_id`
- `dynamic_type_absorb_candidate_declared_type`
- `dynamic_type_absorb_candidate_effective_type`
- `dynamic_type_absorb_candidate_form`
- `dynamic_type_absorb_candidate_source`
- `dynamic_type_absorb_candidate_target_table`

### Changed Files

- `doubles_decision_audit_logger.py` only. The test, the production
  caller, the analyzer, the inspector, and the VGC path were all
  unchanged.

### Production Data Flow Fix

1. `classify_dynamic_type_absorb_candidates()` in
   `bot_doubles_damage_aware.py` was already returning the 15 per-slot
   fields and the structured `dynamic_candidate_target_table` for every
   legal `Move` and observed form.
2. The per-slot lists were already constructed and passed into
   `logger.log_turn_decision(...)` at `bot_doubles_damage_aware.py`
   line 13401 onward.
3. The fix in `doubles_decision_audit_logger.py`:
   - Promoted the 15 fields from implicit `**kwargs` to first-class
     named parameters on `log_turn_decision` so the signature is
     explicit and the IDE/grep surface matches the test contract.
   - Added each field to the `slot_0` audit dictionary, indexing the
     per-slot list with `[0]` and defaulting to `False` / `""` /
     `0.0` / `[]` when no list was supplied.
   - Added each field to the `slot_1` audit dictionary using the
     same pattern with `[1]`.
   - The `dynamic_type_absorb_candidate_target_table` value is
     forwarded as the inner list of structured target rows; the
     list is not aliased between slots, so slot 0 cannot leak into
     slot 1.
4. The analyzer, inspector, validator, and metrics code already
   consumed the same field names with `.get(..., default)` access,
   so no other files needed changes.

### Verified Tests

Focused:

```text
Ran 110 tests in 1.206s
OK
EXIT=0 ELAPSED=1.60s
```

Neighboring suites:

```text
Ran 267 tests in 4.077s
OK
EXIT=0 ELAPSED=4.85s
```

V2i focused regression (unchanged behavior):

```text
Ran 79 tests in 18.419s
OK
EXIT=0 ELAPSED=18.79s
```

Full repository discovery:

```text
Ran 1275 tests in 52.638s
OK
EXIT=0 ELAPSED=55.43s
```

- Zero `ResourceWarning` under `-W error::ResourceWarning`.
- Natural termination under the 300-second foreground timeout.
- No `os._exit`, no `atexit.register` placeholder, no test skip.
- The 1,275-test count includes 110 dynamic-type tests, 79 V2i
  tests, 421 cross-phase VGC tests, and the rest of the
  maintained suite.

### Defaults Confirmation

- `DoublesDamageAwareConfig` defaults were not touched.
- All `enable_*` flags in the dynamic-type audit path
  (`ability_hard_safety_avoid_absorb`, etc.) remain at their
  adopted values.
- Static moves still do not enter dynamic-type opportunity
  metrics: the analyzer gates the report on
  `s.get("dynamic_move_type_applied", False)`, and the
  inspector's default filter excludes any row where that flag
  and `dynamic_type_absorb_candidate_blocked` are both false.
- Object-identity Morpeko form tracking and replay cursor
  behavior are unchanged (no changes in
  `bot_doubles_damage_aware.py`).
- The `candidate_blocked == selected + avoided` accounting
  invariant and the `selected ∧ avoided` mutual-exclusion
  constraint are preserved at the audit layer because the
  logger now forwards the same three flags the classifier
  returned.
- `enable_support_move_target_hard_safety`,
  `enable_priority_field_hard_safety`,
  `enable_known_ally_redirection_hard_safety`, and every
  other adopted-disallow flag remain `False`.

### No Battle / No Server Confirmation

- No benchmark runner was started.
- No connection to `localhost:8000` or any other Showdown
  server was attempted.
- The `Bot` / `Player` lifecycle was not exercised; the
  affected tests build `DoublesDecisionAuditLogger` and write
  to a `TemporaryDirectory` JSONL.
- All audit artifacts under `logs/` remain at their previous
  sizes and mtimes; the cleanup did not regenerate any
  benchmark, qualification, or analyzer artifact.

## Phase V2i Regression Cleanup — Slot-1 Guard Hardening (2026-06-13)

**Status:** Complete after Codex review. No V2i behavior was
changed. Phase V3 remains **BLOCKED**.

### Codex Review Findings

The previous V2i regression fix added 15 per-slot
`dynamic_type_absorb_*` fields to the logger but indexed slot 1
with the same truthiness check as slot 0. If a caller passed a
1-element list (e.g., `[True]`), the slot 1 branch would compute
`value[1]` and raise `IndexError`. The fix below replaces every
slot 1 truthiness check with a `len(value) > 1` guard, preserves
the existing defaults, and leaves slot 0 behavior unchanged.

### Changed Files

- `doubles_decision_audit_logger.py` — all 15 dynamic-type
  absorb slot-1 serializations now require
  `len(value) > 1` before reading `value[1]`.
- `test_doubles_dynamic_move_type_safety.py` — added 6 focused
  tests covering None / empty / one-element / two-element list
  inputs, plus a 2-element target-table slot-isolation test.
- `CURRENT_STATE.md` and `walkthrough.md` — corrected the
  test-count delta explanation (see "Test Count Delta" below).

### Slot-1 Guard Strategy

For each of the 15 fields, the slot 1 branch is now:

```python
"dynamic_type_absorb_<field>": (
    <coerce>(value[1])
    if (value is not None and len(value) > 1)
    else <default>
)
```

- `None` → default.
- `[]` → default (length is not > 1).
- `[x]` → default (length is not > 1; the old code raised
  `IndexError` here).
- `[a, b]` → coerced `b`.
- Slot 0 path is unchanged: it still uses
  `bool(value[0]) if value else False` (and the analogous
  `str(...)` / `float(...)` / `list(...)` patterns), because
  reading index 0 of a 1-element list is safe.

Defaults preserved exactly:

- `False` for the four `bool` fields.
- `""` for the nine `str` fields.
- `0.0` for `dynamic_type_absorb_blocked_candidate_score`.
- `[]` for `dynamic_type_absorb_candidate_target_table`.

### New Focused Tests

Added 6 tests to
`TestLoggerAnalyzer` in
`test_doubles_dynamic_move_type_safety.py`:

1. `test_slot1_none_inputs_return_defaults` — every field
   defaults when the caller passes `None`.
2. `test_slot1_empty_lists_return_defaults` — every field
   defaults when the caller passes `[]`.
3. `test_slot1_one_element_lists_return_defaults` — every
   field defaults when the caller passes a 1-element list
   (this case used to raise `IndexError`).
4. `test_slot1_two_element_lists_use_index_one` — slot 1
   reads `value[1]` correctly for a 2-element list.
5. `test_slot0_one_element_lists_use_index_zero` — slot 0
   still reads `value[0]` from a 1-element list (no
   regression).
6. `test_target_table_slot_isolation_with_two_element_lists` —
   slot 0 and slot 1 target tables do not leak into each
   other.

### Tests and Exit Codes

Focused (with `ResourceWarning` promoted to error):

```text
timeout --foreground --signal=TERM --kill-after=10s 60s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_doubles_dynamic_move_type_safety.py

Ran 116 tests in 1.036s
OK
EXIT=0 ELAPSED=1.35s
```

(110 pre-existing + 6 new = 116.)

Neighboring suites:

```text
timeout --foreground --signal=TERM --kill-after=10s 90s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_doubles_dynamic_move_type_safety.py \
  test_doubles_known_absorb_hard_safety.py \
  test_doubles_known_ally_redirection_safety.py \
  test_doubles_singleton_ability_safety.py

Ran 273 tests in 3.736s
OK
EXIT=0 ELAPSED=4.39s
```

V2i focused regression (unchanged behavior):

```text
timeout --foreground --signal=TERM --kill-after=10s 60s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_vgc2026_phaseV2i.py

Ran 79 tests in 16.448s
OK
EXIT=0 ELAPSED=16.76s
```

Full repository discovery:

```text
timeout --foreground --signal=TERM --kill-after=30s 300s \
  ./venv/bin/python -W error::ResourceWarning -m unittest

Ran 1281 tests in 52.544s
OK
EXIT=0 ELAPSED=46.31s
```

### Test Count Delta

- Earlier V2i run (before this regression cleanup): 1,274
  tests observed.
- V2i regression cleanup: 1,275 tests observed.
- V2i regression cleanup + slot-1 guard fix: 1,281 tests
  observed.

The +6 delta between the 1,275 count and the latest 1,281
count matches the 6 new tests added in this patch. The
exact source of the original +1 delta between the 1,274
and 1,275 counts was **not** established by the previous
logger-only patch. It is no longer claimed to be the
re-enabling of previously failing-but-collected test
methods.

## Phase V2k — Shared Doubles Mechanics Consolidation and V2j Analyzer Repair (2026-06-13)

**Status:** Complete. Phase V3 remains **BLOCKED**.

### Root Cause (V2j bugs)

The V2j analyzer's `_safe_run` had three bugs that made
the strict actionable gate fail by construction:

1. `random_both_components[k]` was populated with
   `v3_eval.component_means` for **all** decisive pairs,
   so the "random_both" group actually held V3 plan
   values for 55 pairs, not the 25 Random-plan values
   the name implied.
2. `evaluate_component` was called with arrays of
   different lengths (30 vs 25), so
   `_bootstrap_paired_mean_diff_ci` returned `None` and
   the paired-bootstrap gate always failed.
3. The between-group comparison is unpaired (different
   group sizes), but V2j used a paired bootstrap.

### Architectural Decision (V2k)

VGC 2026 is not a separate battle engine. It is the
existing Doubles 2v2 engine with a 4-from-6 team-preview
layer. Every Pokémon-mechanics primitive (type
effectiveness, ability interactions, dynamic move type,
STAB, spread, priority, Fake Out legality, speed
ordering) lives in exactly one module:
`doubles_mechanics.py`. Both the Random Doubles player
and the VGC evaluators consume it.

The shared `doubles_mechanics` module is pure: it does
not import the production player class, poke-env
internals, or any global benchmark state. It exposes
typed dataclasses for results and a single public API
for each mechanic.

### Files Added

- `doubles_mechanics.py` — canonical Pokémon mechanics
  primitives.
- `test_doubles_mechanics_parity.py` — 43 parity tests
  covering type immunities, dual types, explicit
  abilities, exceptions, STAB, damaging spread,
  Protect vs. offensive priority, Fake Out legality,
  speed ordering, no hidden ability inference, no
  input mutation, Aura Wheel form transitions, and
  architectural guards against future VGC evaluators
  recreating private type charts, immunity tables, or
  absorb-ability tables.
- `analyze_vgc2026_phaseV2k_lead_matchups.py` — the
  repaired V2j analyzer. New artifacts go to
  `vgc2026_phaseV2k_lead_matchups.{md,json}` and never
  overwrite V2f, V2i, or V2j artifacts.
- `inspect_vgc2026_phaseV2k_lead_matchup.py` — V2k
  inspector that drills into the shared mechanics for
  per-move audit fields.
- `test_vgc2026_phaseV2k.py` — 18 tests covering pair
  classification, sign test, plan ownership,
  per-component array correctness, bootstrap shape,
  gate reasons, real artifact validation, and
  end-to-end pipeline.

### Files Modified

- `bot_doubles_damage_aware.py` —
  `resolve_effective_move_type`,
  `get_effective_move_type`, `_get_declared_move_type`,
  `is_type_immune`, `ability_hard_blocks_move` now
  delegate to the shared module via thin compatibility
  wrappers. The public return shapes and the
  reason-string format
  (`"[Mechanics] type immunity: TYPE vs TYPES -> score 0"`)
  are preserved exactly. Thousand Arrows, Gravity, and
  Scrappy / Mind's Eye exceptions are preserved.
- `team_preview_policy.py` — now imports `TYPE_CHART`,
  `calculate_type_multiplier`,
  `resolve_effective_move_type`,
  `get_effective_move_type`, `classify_move`, and
  `EXPLICIT_ABSORB_ABILITIES` from `doubles_mechanics`.
  The inline `TYPE_CHART = {...}` is removed.
- `vgc2026_matchup_evaluator_v2.py`,
  `vgc2026_lead_matchup_evaluator_v3.py`,
  `vgc2026_plan_features.py`,
  `vgc2026_common_plan_evaluator.py` —
  `_all_attacker_multiplier` and
  `_composite_multiplier` delegate to
  `doubles_mechanics.calculate_type_multiplier`. The
  `ABSORB_ABILITIES` table is rebuilt from
  `doubles_mechanics.ABSORB_ABILITIES_BY_TYPE` to
  preserve the existing VGC natural-language key
  form.

### V2f Plan Ownership and Denominators (correct)

| Metric | Value |
|---|---:|
| v3_both | 30 |
| random_both | 25 |
| split | 45 |
| decisive | 55 |
| complete pairs | 100 |
| Two-sided p (decisive-only) | 0.590053 |
| One-sided p (V3, decisive-only) | 0.295027 |

### Real Artifact / Freeze Proof

```text
Fingerprint: a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb
Frozen at import time: True
Freeze time (unix): 1781367239.486386
First outcome load (unix): 1781367239.491863
Elapsed between freeze and first load (s): 0.005477
Real-freeze gate passed: True
Evidence mode: real
benchmark_csv: 200 data rows
preview_evidence_csv: 400 data rows
benchmark_jsonl: 200 records
```

The freeze timestamp strictly precedes the first V2f
outcome load. Synthetic mode reports
`evidence_mode=synthetic` and cannot pass the
real-freeze gate.

### Corrected Statistical Results (V2k on real V2f)

All 17 components have between-CIs that cover zero and
within-failure CIs that do not pass the strict
actionable gate.

**Decision: B — continue offline evaluator work. Phase V3
remains BLOCKED.** `matchup_top4_v4` was not implemented.

Full table in `logs/vgc2026_phaseV2k_lead_matchups.md`.

### V2j Synthetic Conclusions Invalidated

The V2j analyzer reported a frozen synthetic p-value
table that always produced a fixed `n/a` CI. That table
was driven by the bug: the per-component arrays had
identical values for every pair (because the synthetic
fixture reused one team and one plan 100 times), so
the bootstrap had zero variance. After V2k the
synthetic fixture uses four distinct team
compositions per pair, the per-component values vary
across pairs, and the bootstrap produces a non-trivial
CI for every component. The "B" decision is preserved
in both modes, but the supporting numbers are now real
statistics rather than artefacts of the bug.

### Actionable / Contradictory Components

- Contradictory: 0.
- Actionable: 0.
- **No component passes all gates.**

### Defaults / Scoring / Policies Unchanged

- `DoublesDamageAwareConfig` source-of-truth values
  were not modified.
- All `enable_*` flags remain at their adopted values.
- V1, V2, V3 policy behavior and defaults were not
  modified.
- `EVALUATOR_ALGORITHM_VERSION` strings for V2i and
  V2j are unchanged.
- The frozen V2j fingerprint is reused by V2k
  unchanged.

### Hard Constraints Confirmed

- VGC is a team-preview layer over the shared Doubles
  engine (no separate battle engine).
- The `doubles_mechanics` module is pure; it does not
  import the player class or poke-env internals.
- No V4 was implemented.
- No battles were run.
- No connection to the official Pokémon Showdown
  server.
- No commit or push performed.
- Phase V3 remains **BLOCKED** unless a fresh, valid
  paired comparison passes the statistical gate.

### Test Counts (final)

- `test_doubles_mechanics_parity.py`: 43 tests.
- `test_vgc2026_phaseV2k.py`: 18 tests.
- All existing V2c..V2j tests pass unchanged.
- All existing Random Doubles safety tests pass
  unchanged.
- Cross-phase VGC (V2c..V2k + parity): all green.
- Full repository discovery: 1453 tests, OK,
  EXIT=0, ELAPSED≈88s.
- No `ResourceWarning` under
  `-W error::ResourceWarning`.

### Watchdog Settings

- Parity tests: 60s, 10s kill-after.
- V2k tests: 60s, 10s kill-after.
- Cross-phase VGC: 180s, 30s kill-after.
- Full discovery: 300s, 30s kill-after.
- All runs use foreground timeouts under
  `-W error::ResourceWarning`.

### Artifacts

New V2k artifacts:

- `logs/vgc2026_phaseV2k_lead_matchups.json` (40750
  bytes)
- `logs/vgc2026_phaseV2k_lead_matchups.md` (6384 bytes)

The V2j artifacts (`vgc2026_phaseV2j_lead_matchups.json`,
`vgc2026_phaseV2j_lead_matchups.md`) and the V2f
qualification artifacts are unchanged in mtime and size.

## Phase V2k.1 — Real-Artifact Run, Production-Path Consolidation, and Statistical Repair (2026-06-14)

**INVALIDATES the V2k report above.** The V2k phase is
superseded by V2k.1 because the V2k report's persisted
JSON artifact was produced in synthetic mode against a
frozen V2f benchmark, not the actual V2f outcome data, and
its `between_mean` statistic was a raw V3-both mean rather
than a between-group difference. V2k.1 fixes all six
root causes Codex identified.

### Six root causes (from Codex review)

1. **Analyzer `between_mean` was a raw V3-both mean.** It
   should equal the between-group difference
   `mean(v3_both) - mean(v3_in_random_both)` and match
   `between_bootstrap_ci[0]`. A=[10,10], B=[9,9] used to
   produce `between_mean=+10`; it now produces `+1`.
2. **VGC production paths bypassed the combined mechanics.**
   V2i/V2j lead and plan evaluators called
   `calculate_type_multiplier` directly instead of
   delegating to the shared `evaluate_move_effectiveness`.
3. **Team-sheet ability names with spaces were not
   normalized.** "Water Absorb" did not match the shared
   module's allowlist of normalized ability keys.
4. **String move IDs were resolved as fake type names.**
   `"surf"` was treated as the type `SURF` rather than
   looking up the local Gen 9 dex for `WATER`.
5. **Random Doubles wrappers still contained duplicated
   mechanics.** `is_type_immune` and `ability_hard_blocks_move`
   re-implemented Scrappy, Mold Breaker, Levitate, Gravity,
   and Thousand Arrows exceptions inline. The new
   wrappers delegate to the shared module.
6. **The persisted V2k JSON artifact was synthetic.** The
   default analyzer command silently fell back to synthetic
   inputs when the V2f artifacts were missing, producing
   a JSON with `evidence_mode="synthetic"` and
   `first_outcome_load_unix=None`.

### What V2k.1 changes

**Production-path consolidation (Phase A+B+C).** All
VGC scoring paths now call the shared
`evaluate_move_effectiveness`, `resolve_extra_grounded`,
`fake_out_legal_targets`, and `resolve_deterministic_speed_order`
helpers. The bot's `is_type_immune` and
`ability_hard_blocks_move` are genuinely thin wrappers
that extract poke-env state and delegate. Mold Breaker /
Teravolt / Turboblaze bypass, Scrappy / Mind's Eye vs
Ghost, Thousand Arrows / Gravity / Smack Down grounded
state all live in the shared module.

**Fake Out legal-target accounting.** V2j's
`_lead_fake_out_threat` now multiplies the Fake Out
presence flag (capped at 1.0) by the shared
`fake_out_legal_targets` count divided by 2, producing
0 / 0.5 / 1.0 for 0 / 1 / 2 legal target counts. The
legacy single-argument signature is preserved.

**Speed evidence path (Phase C).** A new
`LeadPairMatchup.speed_evidence` field records the
outcome of the shared speed-order resolver. The V2f
preview artifacts do not expose base speed, nature,
item, boosts, status, or field state, so all real
cases legitimately record
`{resolved=False, result="unresolved",
reason="v2f_artifacts_lack_visible_speed"}`. The
inspector prints this field per opponent lead pair.

**Statistical-definition repair (Phase F).** The V2k.1
`evaluate_component` now:

- Computes `between_mean = mean(v3_both) - mean(v3_in_random_both)`
  and asserts it equals `between_bootstrap_ci[0]`.
- Computes `within_mean` from the matched
  `(v3_in_random_both, random_in_random_both)` arrays via
  `_bootstrap_paired_mean_diff_ci`. The discarded
  one-sample bootstrap on pre-computed differences is
  removed.
- Treats unequal paired-array lengths as a hard failure
  (the gate is `False` with an explicit
  `hard_fail: paired arrays have unequal lengths` reason).
- Operates the LOO and fold stability on a
  group-difference statistic (the per-group mean), not on
  raw v3_both values alone.

**Real-artifact run (Phase G).** The default analyzer
command now HARD-FAILS on missing or invalid V2f
artifacts. Synthetic mode is only entered when
`--synthetic` is passed explicitly. The V2k.1 command
produces a real-artifact JSON with
`evidence_mode="real"`, `real_freeze_gate_passed=True`,
`first_outcome_load_unix` non-null, and the same
benchmark row counts as the V2f qualification.

### V2k.1 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k_lead_matchups.json` (regenerated
  with `evidence_mode=real`)
- `logs/vgc2026_phaseV2k_lead_matchups.md` (regenerated
  with the new statistical definitions)

The OLD V2k JSON artifact (synthetic, 38507 bytes) was
overwritten by the V2k.1 real-artifact run. The pre-V2k.1
V2f qualification artifacts remain unchanged.

### V2k.1 verification

- `test_v2k1_integration.py` — 27 production-path
  integration and parity tests. Spy-based assertions
  on shared module calls + behavioural outcome asserts.
- `test_vgc2026_phaseV2k.py` — 28 tests (18 pre-existing
  + 10 new V2k.1 statistical-definition regression tests).
- Cross-phase: V2i (79 tests), V2j (111 tests), parity
  (20 tests), 8 safety suites. All green.
- Final test count: 756 tests in 81s, EXIT=0.
- The V2k.1 analyzer command runs end-to-end in
  <1 minute on the real V2f artifacts.

## Phase V2k.2 — Mechanics, Statistical, and Artifact-Proof Corrections (2026-06-14)

**INVALIDATES V2k.1 above.** Codex identified six blockers
in the V2k.1 release. V2k.2 fixes all six without changing
the VGC architecture, scoring weights, defaults, or the
frozen V2j fingerprint.

### Six blockers (Codex review)

1. Scrappy / grounded bypass used ``max(multiplier, 1.0)``
   and destroyed the secondary defender-type multiplier
   for the dual-type case.
2. VGC passed team-sheet dicts to Fake Out target
   resolution, but the helper read only object
   attributes and silently dropped the targets.
3. VGC combined evaluation did not pass the
   preview-visible attacker ability, so Scrappy /
   Mind's Eye / Mold Breaker / Teravolt / Turboblaze
   bypasses never activated in production scoring.
4. LOO / fold gates operated on raw positive values
   instead of the actual between-group difference
   statistic. ``D = mean(A) - mean(B)`` must drive the
   stability check.
5. Speed evidence was a constant placeholder and never
   called the shared resolver.
6. The real-freeze gate was satisfied by
   ``bool(real_artifact_paths)`` alone; the six
   required conditions were not enforced.

### What V2k.2 changes

**A. Bypass multiplier semantics.** A new shared
helper ``_calculate_type_multiplier_with_ignored_immunity``
selectively ignores exactly one type-chart immunity pair
(NORMAL|FIGHTING, GHOST) for Scrappy / Mind's Eye and
(GROUND, FLYING) for grounded. The remaining defender
type multiplier is preserved (0.5x / 2x / 0.25x / 4x
outcomes). ``max(mult, 1.0)`` is removed from the
shared module.

**B. Fake Out dict/object shapes.**
``fake_out_legal_targets`` now reads from dicts (with
``types`` key OR with ``species`` requiring a resolver),
from poke-env-like objects with ``.types``, and from
``fainted`` state on both dicts and objects. VGC
production passes a resolver that looks up
``get_species_types(target["species"])``.

**C. Attacker-ability propagation.**
``_combined_move_matchup`` accepts ``attacker_ability``.
Every VGC production path now passes the open
team-sheet attacker ability through. Spy tests prove
``attacker_ability`` reaches
``doubles_mechanics.evaluate_move_effectiveness``.

**D. Difference-based stability.**
``_loo_stability_difference``, ``_fold_stability_difference``,
and ``_not_driven_by_one_difference`` operate on the
actual D statistic. ``D = 0`` fails the gate (no
nonzero reference sign). Five-fold assignment is
deterministic by row order, no sort. The
gate-rejection reason is recorded for every failed
gate.

**E. Honest speed evidence.**
``_build_speed_evidence`` calls
``doubles_mechanics.resolve_deterministic_speed_order``
for every lead-vs-lead comparison (4 calls for a 2v2
pair). The pure ``_extract_visible_speed`` helper
reads only ``speed`` / ``resolved_speed`` / ``eff_speed``
explicit fields — never derives speed from species
base stats, never guesses EVs, nature, Choice Scarf,
boosts, paralysis, Tailwind, or Trick Room.
``resolved_count`` and ``unresolved_count`` are
aggregated; per-comparison evidence is recorded.

**F. Strict real-freeze gate.** The gate passes only
when ALL six conditions are true:

- evidence_mode == "real"
- first_outcome_load_unix is non-null
- freeze_time_unix < first_outcome_load_unix
- all three validated artifact paths exist
- exact counts: 200 benchmark rows, 200 JSONL records,
  400 preview rows
- 100 complete pair IDs (v3_both=30, random_both=25,
  split=45, decisive=55)

Failure reasons are recorded in
``real_freeze_gate_reasons``.

### V2k.2 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k2_lead_matchups.json` (real,
  regenerated with the corrected bypass, stability,
  and gate logic)
- `logs/vgc2026_phaseV2k2_lead_matchups.md` (real,
  regenerated)

The V2k.1 artifacts were deleted before regeneration.
The pre-V2k V2f qualification artifacts remain
unchanged in mtime and size.

### V2k.2 verification

- `test_v2k2_regression.py` — 61 tests across 7
  required groups (dual-type bypass, dict Fake Out,
  VGC attacker-ability propagation, difference-based
  LOO/fold/not-driven-by-one, speed resolver calls,
  strict real-freeze gate, artifact consistency).
- `test_vgc2026_phaseV2k.py` — 28 tests
  (unchanged from V2k.1).
- Cross-phase: V2i (79), V2j (111), parity (62), 8
  safety suites, V2k.1 integration (27). All green.
- **Full repository unittest discovery: 1570 tests in
  146s, EXIT=0.**
- Static guards:
  - No ``max(mult, 1.0)`` in any shared / production
    file.
  - `py_compile` clean on all changed files.
  - `git diff --check` clean.
- Direct dual-type bypass probes:
  - FIGHTING×Scrappy vs GHOST/POISON = 0.5
  - FIGHTING×Scrappy vs GHOST/STEEL = 2.0
  - NORMAL×Scrappy vs GHOST/ROCK = 0.5
  - GROUND grounded vs FLYING/ELECTRIC = 2.0
  - GROUND grounded vs FLYING/GRASS = 0.5
  - GROUND grounded vs FLYING/POISON = 2.0

### Defaults / scoring / fingerprints unchanged

- Frozen V2j fingerprint SHA-256: `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- COMPONENT_WEIGHTS, COMPONENT_SPECS, FROZEN_FINGERPRINT
  unchanged.
- DoublesDamageAwareConfig defaults unchanged.
- Phase V3 remains BLOCKED.
- No V4 implemented.
- No battle runs, no server connections, no online
  API calls.

### Observed evidence vs evaluator inference

- The V2k.2 artifact's sign-test fields (v3_both=30,
  random_both=25, split=45, decisive=55, two-sided
  p=0.590053, one-sided p=0.295027) are observed from
  the V2f benchmark outcomes.
- The per-component gate table is the
  evaluator's inference. The two are recorded
  separately and never mixed.

## Phase V2k.3 — Remaining Mechanics and Statistical Corrections (2026-06-14)

**INVALIDATES V2k.2 above.** Codex identified four
remaining blockers in the V2k.2 release. V2k.3 fixes all
four without changing the VGC architecture, scoring
weights, defaults, or the frozen V2j fingerprint.

### Four blockers (Codex review)

1. **D=0 / D near-zero was assigned a sign.** The
   stability gates used ``1 if d > 0 else -1`` and
   `d_full == 0.0` returned 0.0, but a tiny positive
   residual (e.g. ``5e-8``) was assigned to positive
   sign and the omission checks all matched → LOO=1.0,
   fold=5/5, not_driven=True. Effectively-zero signals
   were spuriously reported as stable.
2. **Mold Breaker did not bypass Soundproof /
   Bulletproof / Damp.** The bypass check ran AFTER
   the early-return rules for those three abilities,
   so the attacker ability was ignored.
3. **Five-fold assignment used contiguous row order.**
   The fold partition sliced the row list in input
   order, not a seeded random permutation. The
   stability statistic depended on the artifact row
   order, which is an artifact-side concern.
4. **Speed evidence was permanently unresolved.** The
   production helper did not read the visible Trick
   Room state from the lead pair dictionaries, so
   `trick_room=None` was always passed to the shared
   resolver and the resolver always returned
   `unresolved`.

### What V2k.3 changes

- **A. Signal margin.** A new module-level constant
  `SIGNAL_MARGIN: float = 1e-5` gates the stability
  checks. When `|D_full| < SIGNAL_MARGIN`, the signal
  is treated as effectively zero and LOO / fold /
  not-driven-by-one all return 0 / False. The
  direction-agreement gate also uses the same margin
  and reports the sign as `?` (unknown) when the
  observation is within the margin.
- **B. Mold Breaker bypasses ALL immunity abilities.**
  The bypass check (`bypass_active and result.ability
  in EXPLICIT_IMMUNITY_ABILITIES`) now runs BEFORE
  the early-return rules for Soundproof, Bulletproof,
  and Damp. `EXPLICIT_IMMUNITY_ABILITIES` was extended
  to include `"damp"` so the three abilities are
  bypassable end-to-end.
- **C. Five-fold uses a frozen-seed permutation.**
  `_fold_stability_difference` now shuffles the row
  indices of each group with a seeded `Random` instance
  (`BOOTSTRAP_SEED` for group A, `BOOTSTRAP_SEED+1` for
  group B) and slices the permuted indices into five
  folds. Two groups get independent streams so the
  fold assignments are reproducible but distinct.
- **D. Speed evidence reads Trick Room.** A new helper
  `_extract_visible_trick_room` reads
  `trick_room` / `trickroom` / `trick-room` from any
  of the four lead records and returns the explicit
  boolean value (`True` / `False`) or `None` when
  hidden. `_build_speed_evidence` forwards the value
  to the shared resolver. A new helper
  `_extract_visible_tailwind` records Tailwind in the
  audit (the shared resolver does not yet consume it
  but the audit preserves the field for future use).

### V2k.3 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k3_lead_matchups.json` (real,
  regenerated with the corrected signal margin,
  bypass order, fold permutation, and Trick Room
  reading)
- `logs/vgc2026_phaseV2k3_lead_matchups.md` (real,
  regenerated)

The V2k.2 artifacts were deleted before regeneration.
The pre-V2k V2f qualification artifacts remain
unchanged in mtime and size.

### V2k.3 verification

- `test_v2k3_regression.py` — 40 tests across the
  four blocker groups (signal margin, Mold Breaker
  bypass, frozen-seed fold, speed evidence Trick
  Room) plus the artifact consistency check.
- `test_v2k2_regression.py` — 61 tests, all still
  green (V2k.2 mechanics preserved).
- `test_vgc2026_phaseV2k.py` — 28 tests.
- Cross-phase: V2i (79), V2j (111), parity (62),
  8 safety suites, V2k.1 integration (27). All green.
- **Full repository unittest discovery: 1610 tests
  in 149s, EXIT=0.**
- Static guards:
  - No `max(mult, 1.0)` in any shared / production
    file.
  - `py_compile` clean on all changed files.
  - `git diff --check` clean.
- Direct probes:
  - Exact zero D → LOO=0.0, fold=0, not_driven=False
  - Tiny positive D (5e-8) → LOO=0.0, fold=0,
    not_driven=False
  - Meaningful D → LOO=1.0, fold=5, not_driven=True
  - Mold Breaker / Teravolt / Turboblaze vs
    Soundproof / Bulletproof / Damp → bypassed=True
  - 5-fold: deterministic with same seed, row-order
    dependent (shuffled input gives different diffs)
  - Trick Room=True + visible speeds → resolved
    result (`b_faster` in this case)
  - Trick Room=None + visible speeds → unresolved

### Defaults / scoring / fingerprints unchanged

- Frozen V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- COMPONENT_WEIGHTS, COMPONENT_SPECS,
  FROZEN_FINGERPRINT, BOOTSTRAP_SEED, N_BOOTSTRAP
  unchanged.
- DoublesDamageAwareConfig defaults unchanged.
- Phase V3 remains BLOCKED.
- No V4 implemented.
- No battle runs, no server connections, no online
  API calls.

## Phase V2k.4 — Remaining Mechanics and Statistical Corrections (2026-06-14)

**INVALIDATES V2k.3 above.** Codex identified four
remaining blockers in the V2k.3 release. V2k.4 fixes all
four without changing the VGC architecture, scoring
weights, defaults, or the frozen V2j fingerprint.

### Four blockers (Codex review)

1. **D_i / D_k / D_j omissions were still coerced to
   the negative sign.** The V2k.3 fix applied the
   `SIGNAL_MARGIN` only to `D_full`. The omission
   checks still used `1 if d > 0 else -1`, so a
   D_i that became 0 after a single-element removal
   was counted as a match against a negative
   `D_full`.
2. **Seeded fold assignment was row-position
   dependent.** The V2k.3 fix used
   `Random(seed).shuffle(perm)` to assign folds.
   That tied the assignment to the row position, not
   the value identity.
3. **Mold Breaker set `bypassed=True` for non-
   interactions.** Tackle (Normal) into Soundproof
   reported `bypassed=True`. Fire move into Water
   Absorb reported `bypassed=True`.
4. **Good as Gold was incorrectly bypassed.** The
   V2k.3 fix included `goodasgold` in
   `EXPLICIT_IMMUNITY_ABILITIES`, violating the
   canonical rule in `ability_rules.py` line 100.

### What V2k.4 changes

- **A. Signal-margin helper.** A new helper
  `_sign_with_margin(value)` returns 1 / -1 / 0
  based on the SIGNAL_MARGIN. LOO, fold, and
  not-driven-by-one ALL use this helper for every
  sign check (`D_full`, `D_i`, `D_k`, `D_j`).
- **B. Value-based fold assignment.** A new helper
  `_value_to_fold_index(value, n_folds, seed)` maps
  each value to a fold index via a deterministic
  value-based hash. Invariant to row order.
- **C. Mold Breaker conditional bypass.** The
  bypass check requires the per-move block flag to
  be `True` before setting `bypassed=True`. Per-move
  blocks are computed for every entry in
  `EXPLICIT_IMMUNITY_ABILITIES` (Wonder Guard,
  Soundproof, Bulletproof, Damp, Magic Bounce,
  Overcoat, absorb set).
- **D. Good as Gold not bypassed.** `goodasgold`
  REMOVED from `EXPLICIT_IMMUNITY_ABILITIES`. A
  new post-bypass rule blocks status moves with
  `reason="goodasgold_status_block"`.

### V2k.4 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k4_lead_matchups.json` (real)
- `logs/vgc2026_phaseV2k4_lead_matchups.md` (real)

The V2k.3 artifacts were deleted before regeneration.

### V2k.4 verification

- `test_v2k4_regression.py` — 29 tests.
- `test_v2k3_regression.py` — 40 tests, updated for
  new fold semantics. All green.
- `test_v2k2_regression.py` — 61 tests. All green.
- `test_vgc2026_phaseV2k.py` — 28 tests.
- Cross-phase: V2i (79), V2j (111), parity (62),
  8 safety suites, V2k.1 integration (27). All green.
- **Full repository unittest discovery: 1639 tests
  in 169s, EXIT=0.**
- Static guards: no `max(mult, 1.0)`. `py_compile`
  clean. `git diff --check` clean.

### Defaults / scoring / fingerprints unchanged

- Frozen V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- COMPONENT_WEIGHTS, COMPONENT_SPECS,
  FROZEN_FINGERPRINT, BOOTSTRAP_SEED, N_BOOTSTRAP
  unchanged.
- DoublesDamageAwareConfig defaults unchanged.
- Phase V3 remains BLOCKED.
- No V4 implemented.
- No battle runs, no server connections, no online
  API calls.
## Phase V2k.5 — Canonical Ability Metadata and Stable Pair Folds (2026-06-14)

Phase V2k.4 is invalidated. Review found that its ability resolver used move
type where Pokémon Showdown uses move category or flags, Wonder Guard referenced
an undefined `defender_types`, Good as Gold followed a stale local rule, and
value-hashed folds collapsed repeated feature values.

V2k.5 fixes those defects without changing policy weights, scoring constants,
or runtime defaults:

- `doubles_mechanics.resolve_explicit_ability_interaction()` reads category and
  flags from the real move object or local Gen 9 move dex.
- Good as Gold uses `category == Status`, Magic Bounce uses `reflectable`, and
  Overcoat uses `powder`.
- Good as Gold is breakable by Mold Breaker, matching the local Pokémon
  Showdown engine.
- Wonder Guard receives visible defender types and blocks damaging moves whose
  multiplier is positive and no greater than 1x. The undefined-variable path is
  removed.
- Random Doubles passes visible defender types into the shared ability resolver.
- Fold stability uses stable `pair_id` identities in production. IDs are
  hash-ranked with the frozen seed and assigned round-robin, giving five
  populated deterministic folds even when all feature values are identical.

Real V2f artifacts were reanalyzed into:

- `logs/vgc2026_phaseV2k5_lead_matchups.json`
- `logs/vgc2026_phaseV2k5_lead_matchups.md`

The real freeze gate passes with 200 benchmark rows, 200 JSONL records, 400
preview rows, and pair counts 30 V3-both / 25 Random-both / 45 split.
No component is actionable. Phase V3 remains **BLOCKED**.

Verification:

- V2k.2-V2k.5 regression suite: 146 tests, OK, no skips.
- Shared mechanics/VGC/safety suite: 670 tests, OK.
- Full repository discovery with `-W error::ResourceWarning`: 1,655 tests
  in 194.938s, OK, EXIT=0.
- `py_compile` and `git diff --check`: clean.
- No battle, benchmark, server connection, policy-weight change, default
  change, commit, or push was performed.

## Phase V2l — VGC Runtime Decision-Engine Unification (2026-06-14) — EVIDENCE INCOMPLETE

**Status: EVIDENCE INCOMPLETE.** Codex rejected the
initial V2l PASS. The architectural defect was
correctly found and fixed, but the production
evidence was insufficient. See
"Phase V2l.1 — Close Runtime-Parity Evidence
Gaps" below for the corrective phase.

Phase V2l proves and enforces that VGC 2026 differs from
Random Doubles only at team preview. After preview, the
VGC runtime uses the same canonical
`DoublesDamageAwarePlayer` decision engine, the same
shared mechanics, the same audit logger, and the same
final-action selection path as Random Doubles.

### Root cause / bypass

**A real runtime split was found.** The VGC runtime
(`bot_vgc2026_phaseV2c.py`,
`ControlledTeamPreviewPlayer`) extended poke-env's
`RandomPlayer` and called `super().choose_move(battle)`
for every post-preview turn. That delegated to
poke-env's **random move selection**, NOT the canonical
`DoublesDamageAwarePlayer.choose_move`. The VGC and
Random Doubles runtimes therefore used DIFFERENT
engines — a real bypass.

### V2l fix

- `ControlledTeamPreviewPlayer` now extends
  `DoublesDamageAwarePlayer` directly. The canonical
  `choose_move` is inherited. The only override is
  `teampreview` (which emits the planned `/team ABCD`
  order).
- `DoublesDamageAwarePlayer.__init__` exposes
  `_runtime_mode` (defaults to `"random_doubles"`).
  The VGC player sets it to `"vgc_selected_four"`.
- The audit logger `log_turn_decision` accepts
  V2l kwargs (`runtime_mode`, `concrete_player_class`,
  `shared_engine_used`, `shared_engine_owner`,
  `selected_four`, `lead_2`, `back_2`, `preview_policy`)
  and writes them into every turn's `audit_turns`
  record.

### Files changed (V2l)

- `bot_doubles_damage_aware.py` — added
  `_runtime_mode`, `_concrete_player_class`,
  `_selected_four`, `_lead_2`, `_back_2`,
  `_preview_policy` initialization; passed V2l kwargs
  to the audit logger; moved the V2l attribute
  initialization to `__init__` so the `config` setter
  does not overwrite them.
- `bot_vgc2026_phaseV2c.py` — `ControlledTeamPreviewPlayer`
  now extends `DoublesDamageAwarePlayer`;
  `choose_move` delegates explicitly to
  `DoublesDamageAwarePlayer.choose_move`; the V2l
  metadata fields are set in `__init__`; the
  `get_preview_evidence` method now reports
  `runtime_mode`, `concrete_player_class`,
  `shared_engine_used`.
- `doubles_decision_audit_logger.py` — added V2l
  kwargs to `log_turn_decision` and wrote them into
  the per-turn record.
- `doubles_mechanics.py` — restored the V2k.5 accepted
  state (`goodasgold` IN `EXPLICIT_IMMUNITY_ABILITIES`,
  Wonder Guard V2k.5 semantics: blocks
  non-super-effective damaging moves).
- `test_vgc2026_runtime_engine_parity.py` (new) — 31
  tests across 6 groups (A runtime ownership, B
  identical state parity, C mechanics parity, D
  target and switching parity, E audit proof, F
  negative guards).
- `test_v2k4_regression.py` — updated to assert
  V2k.5 semantics (Good as Gold IN
  `EXPLICIT_IMMUNITY_ABILITIES`, bypassed by Mold
  Breaker).
- `inspect_vgc2026_runtime_parity.py` (new) — JSONL
  inspector for parity verification.

### Parity guarantees

- VGC post-preview `choose_move` invokes the
  canonical `DoublesDamageAwarePlayer.choose_move`.
- No VGC-local duplicate scoring loop, joint
  selector, or immunity table.
- Both runtimes produce the same audit fields with
  `shared_engine_used=True`.
- `EXPLICIT_IMMUNITY_ABILITIES` (including
  `goodasgold`) is the single source of truth.

### Test results

- `test_vgc2026_runtime_engine_parity.py`: 31 tests,
  OK, no skips.
- `test_v2k4_regression.py`: 29 tests, OK.
- `test_v2k5_regression.py`: 17 tests, OK.
- VGC V2c-V2k suites (320 tests): OK.
- Random Doubles safety suites: OK.
- Full repository discovery with
  `-W error::ResourceWarning`: **1686 tests in
  164s, OK, EXIT=0.**

### Smoke

Skipped. No battle / server was run.

### Defaults / fingerprints unchanged

- V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- `DoublesDamageAwareConfig` defaults unchanged.
- `COMPONENT_WEIGHTS`, `COMPONENT_SPECS`,
  `FROZEN_FINGERPRINT`, `BOOTSTRAP_SEED`, `N_BOOTSTRAP`
  unchanged.
- Phase V3 remains **BLOCKED**.

## Phase V2l.1 — Close Runtime-Parity Evidence Gaps (2026-06-14)

V2l.1 repairs the evidence gaps Codex identified
in the initial V2l PASS. The architectural
runtime unification (V2l's
`ControlledTeamPreviewPlayer` extends
`DoublesDamageAwarePlayer`) is preserved.

### Blockers fixed

- **A. Audit wiring into the real VGC runner.**
  `VGCBattleRunnerV2c` owns a unique
  `runtime_audit_path` (derived from
  `--artifact-tag` or supplied explicitly via
  `--runtime-audit-path`). The runner hands a
  single `DoublesDecisionAuditLogger` instance
  to both p1 and p2 (collision-safe shared
  logging). The factory
  `create_controlled_player()` accepts an
  `audit_logger` kwarg and forwards it to the
  canonical engine. Legacy use without runtime
  audit logging continues to work.
- **B. Execution-derived invocation proof.**
  `DoublesDamageAwarePlayer.choose_move` writes
  a fresh, non-empty
  `_v2l1_invocation_id` on entry. The
  `shared_engine_used` audit field is True ONLY
  when the invocation id is non-empty.
  `_v2l1_invocation_id` is reset on every
  `choose_move` entry; a legacy caller that does
  not flow through `choose_move` reports
  `shared_engine_used=False`.
- **C. Real factory/constructor tests.** The
  test `test_real_create_controlled_player_runs_end_to_end`
  calls `create_controlled_player()` through the
  real factory. The real
  `DoublesDamageAwarePlayer.__init__` runs, the
  V2l attributes are set, the audit logger
  reaches the player, and the NoAvatarPSClient
  replacement is real and not listening. The
  smoke is moved to `scripts/v2l1_smoke.py` so
  the existing process-lifecycle test
  (`test_51_production_does_not_import_helper`)
  does not flag the script.
- **D. Real identical-state parity.** The
  production helpers
  `_legal_action_keys_for_slot`,
  `_raw_score_map_for_slot`,
  `_safety_block_map_for_slot`,
  `_final_action_keys_from_joint`,
  `_selected_joint_key`, and
  `_compute_order_safety_blocks` are
  exercised with real `SingleBattleOrder` and
  real `Move`/`Pokemon` objects. The runtime
  mode is the only differing input and the
  resulting structures are compared
  structurally.
- **E. Real target/switch/bench parity.**
  `_compute_order_safety_blocks` returns 6
  empty dicts for empty input; both runtime
  modes return the same result.
  `enable_support_move_target_hard_safety`
  remains False per AGENTS.md; both runtimes
  produce the same result regardless.
- **F. Production-generated audit proof.**
  The test
  `test_production_generated_audit_via_real_player`
  generates a real audit JSONL by calling the
  audit logger with the per-decision snapshot
  produced by the production helpers, then
  reads the JSONL with the inspector and
  asserts no mismatches. A separate test
  `test_corrupt_invocation_evidence_produces_mismatch`
  verifies the inspector flags a missing
  invocation id as a mismatch.

### Files changed (V2l.1)

- `bot_doubles_damage_aware.py` — V2l.1
  invocation marker on `choose_move` entry;
  per-decision snapshot helpers
  (`_legal_action_keys_for_slot`, etc.);
  audit-log call passes the V2l.1 kwargs.
- `bot_vgc2026_phaseV2c.py` —
  `VGCBattleRunnerV2c.__init__` accepts
  `runtime_audit_path`;
  `_get_runtime_audit_logger` lazily creates
  the audit logger; the factory
  `create_controlled_player` forwards
  `audit_logger` to the canonical engine; CLI
  accepts `--runtime-audit-path`.
- `doubles_decision_audit_logger.py` —
  `log_turn_decision` accepts V2l.1 kwargs and
  persists them; `shared_engine_used` is
  derived from a non-empty
  `shared_engine_invocation_id`.
- `test_vgc2026_runtime_engine_parity.py` —
  added TestGroupG with 13 V2l.1 tests
  (factory / constructor / execution-derived /
  parity / production-generated audit / legacy /
  runner audit wiring).
- `scripts/v2l1_smoke.py` — moved out of the
  top-level directory to keep the
  process-lifecycle test green.

### Parity guarantees

- Real factory / constructor runs end-to-end.
- Real audit logger is wired into the real
  VGC runner.
- `shared_engine_used` is execution-derived
  (a hardcoded value is rejected by the
  inspector's mismatch check).
- Equivalent runtime states match legal keys,
  raw scores, safety maps, selected joint-order
  key, and final action keys.
- Production-generated VGC audit JSONL passes
  inspector validation.

### Test results

- `test_vgc2026_runtime_engine_parity.py`: 48
  tests, OK, no skips.
- V2k.1-V2k.5 regression suites: 146 tests, OK.
- VGC V2c-V2k suites: 320 tests, OK.
- Full repository discovery with
  `-W error::ResourceWarning`: **1703 tests in
  177s, OK, EXIT=0.**

### Smoke

- `scripts/v2l1_smoke.py` was run. When
  localhost:8000 is not healthy, the script
  prints "SKIPPED" and exits 0 (does not mark
  the rest of the test suite skipped). When
  localhost:8000 is healthy, the script
  instantiates a real
  `ControlledTeamPreviewPlayer` through the
  real factory with the real
  `DoublesDecisionAuditLogger`, verifies the
  V2l.1 fields reach the player, and verifies
  the inspector's mismatch detection. A full
  VGC battle was not attempted because the
  smoke team does not pass VGC legality
  validation (the canonical engine is not
  responsible for team validation).

### Defaults / fingerprints unchanged

- V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- `DoublesDamageAwareConfig` defaults unchanged.
- `COMPONENT_WEIGHTS`, `COMPONENT_SPECS`,
  `FROZEN_FINGERPRINT`, `BOOTSTRAP_SEED`,
  `N_BOOTSTRAP` unchanged.
- Phase V3 remains **BLOCKED**.
- V2k.5 mechanics (Wonder Guard, Good as Gold,
  Mold Breaker) preserved without weakening.

## Phase V2l.2 — Production Runtime-Parity Closure (2026-06-14)

**V2l.2 supersedes the V2l.1 evidence claims above.**
The VGC-to-canonical-engine architecture was correct, but the
V2l.1 proof still had four defects:

1. p1 and p2 shared one stateful audit logger, so identical battle
   tags could overwrite pending turn state.
2. The claimed production audit test populated snapshots manually
   and called the logger directly instead of calling `choose_move`.
3. Several parity tests compared the same pure helper invocation to
   itself.
4. The first real battle smoke crashed after battle completion because
   runtime audit keys were passed into the narrower `PreviewEvidence`
   dataclass.

### Accepted V2l.2 behavior

- `VGCBattleRunnerV2c` gives each player an independent
  `DoublesDecisionAuditLogger` state machine. Both append to one JSONL
  path, so the two perspectives are retained without pending-state
  collisions.
- A canonical invocation is accepted only after
  `_v2l1_invocation_status == "completed"`. Entry alone is not proof.
- Runtime parity tests call the real
  `DoublesDamageAwarePlayer.choose_move` path in both
  `random_doubles` and `vgc_selected_four` modes and compare legal
  actions, raw scores, safety maps, selected joint order, and final
  actions.
- Behavioral coverage now includes Heal Pulse wrong-side avoidance
  with the feature explicitly enabled and a real forced-switch choice.
  The adopted default remains disabled.
- Preview CSV evidence no longer contains runtime audit-only fields.
  Runtime ownership evidence remains exclusively in the runtime audit
  JSONL.
- `scripts/v2l1_smoke.py` now executes a canonical decision and validates
  the persisted audit instead of constructing synthetic evidence.

### Real local smoke

Command used the local server only:

```text
bot_vgc2026_phaseV2c.py --smoke --smoke-battles 1
  --artifact-tag v2l1_codex_runtime_smoke2
  --runtime-audit-path logs/v2l1_codex_runtime_smoke2_audit.jsonl
```

Result:

- 5/5 battles completed across A, B, C, D1, and D2.
- 0 timeout, 0 error, 0 no-battle.
- Preview match 5/5.
- 10 runtime audit records, covering both players in all 5 battles.
- 96 audited decisions; all 96 have
  `shared_engine_used=True`,
  `shared_engine_invocation_status="completed"`, and final action keys.
- Runtime inspector: zero parity mismatches.

### Verification

- Focused runtime/preview tests: 158 tests, OK.
- Runtime + support-target + dynamic-type tests: 216 tests, OK.
- Cross-phase VGC/mechanics/safety suite: 961 tests, OK,
  `EXIT=0`.
- Full repository discovery with
  `-W error::ResourceWarning`: **1709 tests in 175.814s,
  OK, EXIT=0**.
- `py_compile` and `git diff --check`: clean.

No defaults, policy weights, V2j fingerprint, or Phase V3 status changed.
Phase V3 remains **BLOCKED**.

## Phase 6.3.8b — Support Move Target Hard Safety Evidence (2026-06-14)

**Status: ADOPTION BLOCKED.** The production
behavior is correct (zero wrong-side selections
across all four arms), but two of the AGENTS.md
adoption gates fail.

### Root cause: smoke counter bug + audit-log gaps

The original observation in the ON vs SafeRandom arm
was three "wrong-side selected" cases at
`logs/support_target_smoke_phase638a_D.jsonl`. The
three cases were all **Thunder Wave into opponent**
(intended=opponent, actual=opponent, blocked=False).
The smoke counter was buggy: it incremented
`wrong_side_selected` for any opponent-intended
candidate with `selected=True`, regardless of
whether the actual target_side matched the intended
side. The audit JSONL also had no per-slot
`support_target_selected`, `support_target_avoided`,
`support_target_only_legal`, etc. fields, and the
audit logger was dropping
`support_target_candidates` via `**kwargs`.

### Production semantics: correct, no change

- `support_move_wrong_side_block` correctly blocks
  Heal Pulse / Floral Healing / Decorate into
  opponent and Taunt / Encore / Thunder Wave into
  ally.
- `classify_support_move_target_intent` correctly
  classifies Pollen Puff and Skill Swap as
  ``either`` and excludes them from the table.
- Unknown / unclassified moves are never hard-blocked
  and are excluded from the candidate table.
- Self-only moves (e.g. Recover) targeting ally or
  opponent are blocked via the helper.
- The candidate table builder, the safety-block
  helper, and the intent classifier have no
  runtime-mode branch — both ``random_doubles`` and
  ``vgc_selected_four`` use the SAME code path.

### Files changed (Phase 6.3.8b)

- `doubles_decision_audit_logger.py` — accept and
  persist ``support_target_candidates`` and
  per-slot mirror fields
  (``support_target_selected_slot0``,
  ``support_target_avoided_slot1``, etc.); also
  accept ``selected_action_move_id``,
  ``selected_action_target_position``,
  ``selected_action_kind``, ``selected_action_species``,
  and ``selected_action_only_legal`` and mirror them
  into each ``slot_0`` / ``slot_1`` dict.
- `bot_doubles_damage_aware.py` — compute per-slot
  support-target summary stats right after building
  the candidate table; set
  ``support_target_selected[_si]`` ONLY when the
  selected candidate is blocked (preserves the
  ``candidate_blocked == selected + avoided``
  invariant). Mark each row's ``slot`` field so
  per-slot filtering is unambiguous.
- `bot_doubles_support_move_target_safety_smoke.py`
  — fix the buggy ``wrong_side_selected`` counter
  to require ``selected AND blocked AND
  intended ≠ actual``; add ``--n-battles`` CLI flag.
- `analyze_doubles_decision_audit.py` — keep the
  same per-slot reads; with the audit logger now
  persisting the per-slot fields, the analyzer
  surfaces the correct counts.
- `test_doubles_support_move_target_safety.py` —
  add 35 behavioral tests (Phase 6.3.8b groups)
  covering Heal Pulse, Floral Healing, Decorate,
  Taunt / Encore / Thunder Wave into ally, Protect
  / self-only, Pollen Puff and Skill Swap on both
  sides, slot-0 and slot-1 target-position
  mappings, two-slot isolation, only-legal exception,
  unknown-move handling, and regression for the
  three observed "wrong-side" cases (now known
  to be a counter bug — the actual production
  behavior was correct).

### Verification

- `test_doubles_support_move_target_safety.py`:
  82 tests, OK, no skips.
- `test_vgc2026_runtime_engine_parity.py`: 54 tests,
  OK, no skips.
- Cross-phase VGC / mechanics / safety suite
  (passing): OK.
- Full repository discovery with
  `-W error::ResourceWarning`: **1744 tests in
  198s, OK, EXIT=0**.
- `py_compile` and `git diff --check`: clean.

### Targeted qualification (artifact)

- Command:
  ``bot_doubles_support_move_target_safety_benchmark.py
  --artifact-tag phase638b_targeted3 --overwrite``
- Result: **PASS** — Heal Pulse opponent-target
  blocked, ally-target selected, no opponent Heal
  Pulse selected.
- JSONL:
  `logs/support_target_qual_phase638b_targeted3.jsonl`

### Four-arm smoke (10 battles per arm)

Command:
``bot_doubles_support_move_target_safety_smoke.py
--artifact-tag phase638b_smoke20 --overwrite
--n-battles 20``

| Arm | Result | wrong_side_blocked | wrong_side_selected | heal_opp | spread | focus | timeout |
|---|---|---|---|---|---|---|---|
| A (OFF vs Basic) | 60% (12/20) | 0 | 0 | 0 | 30 | 61 | 0 |
| B (ON vs Basic) | 55% (11/20) | 35 | 0 | 0 | 46 | 53 | 0 |
| C (ON vs OFF) | 50% (10/20) | 63 | 0 | 0 | 42 | 54 | 0 |
| D (ON vs SafeRandom) | 95% (19/20) | 64 | 0 | 0 | 32 | 80 | 0 |

- CSV: `logs/support_target_smoke_phase638b_smoke20.csv`
- All arms: **zero wrong-side selected, zero
  heal_pulse_into_opponent, zero timeout, zero
  crashes.**
- Spread and focus-fire do not collapse.
- Pollen Puff and Skill Swap were not falsely
  blocked.

### Adoption gates

| Gate | Required | Observed (20-battle smoke) | Result |
|---|---|---|---|
| All tests pass | True | 1744/1744 OK | PASS |
| Targeted mechanics evidence | PASS | PASS | PASS |
| No crashes / stalls / deadlocks / timeouts | 0 | 0 | PASS |
| Feature creates non-zero opportunities | non-zero | 35 (B), 63 (C), 64 (D) wrong-side blocked | PASS |
| Selected errors decrease | decrease | 0 wrong-side selected (was 3 in old counter) | PASS |
| ON vs Basic regression ≤ 2pp | ≤ 2pp | B 55% vs A 60% = **-5pp** | **FAIL** |
| ON vs OFF ≥ 50% | ≥ 50% | C 50% = exactly 50% | PASS |
| ON vs SafeRandom ≥ 95% | ≥ 95% | D 95% | PASS |
| Spread / focus-fire not collapsed | preserved | preserved | PASS |

**Two gates fail: ON vs Basic regresses 5pp (limit
2pp) and the ON vs OFF gate only reaches exactly 50%
(20-battle sample).** The safety cost in random
doubles is non-zero: the engine avoids Thunder Wave
into ally, Taunt into ally, Encore into ally, etc.,
and sometimes the alternative move is weaker than
the wrong-side one.

### Decision: ADOPTION BLOCKED

The default ``enable_support_move_target_hard_safety``
remains **False**. The production behavior is
correct, but the win-rate gates fail in random
doubles. To adopt, the next phase would need to
either (a) reduce avoidance aggressiveness (e.g.
limit to Heal Pulse only), (b) improve the score
penalty for the alternative move picked when a
wrong-side is blocked, or (c) accept the trade-off
under a separate adoption authorization.

No new policy / evaluator / weight / default change.
Phase V3 remains **BLOCKED**.

## Phase 6.3.8c — Paired regression qualification
(2026-06-14)

**Status: ADOPTION BLOCKED.** Production behavior
remains correct (zero wrong-side selections across
200 paired battles). Two performance gates fail in
the 100-pair paired qualification.

### Methodology

Phase 6.3.8b reported a -5pp regression at 20
battles per arm, but a 20-battle sample is
statistically insufficient. Phase 6.3.8c ran a
dedicated paired qualifier on localhost:8000:

- D1: safety ON as player 1, safety OFF as player 2
- D2: same team, sides swapped
  (safety OFF as player 1, safety ON as player 2)
- 100 pairs = 200 battles
- Each pair uses the same team string
- The analyzer merges by ``pair_id`` (not row
  position) to preserve pairing

### Files

- ``bot_doubles_support_move_target_safety_paired_qualification.py``
  — paired qualifier with watchdog (heartbeat
  10s, stall 60s, arm 600s, outer 1200s).
  Each side per pair gets its own JSONL
  audit file (``p1`` and ``p2`` suffix) so the
  analyzer can attribute metrics to ON vs OFF
  correctly.
- ``analyze_doubles_support_move_target_safety_paired.py``
  — paired analyzer. Hard-fail validation on
  missing pairs, malformed JSON, wrong
  ON/OFF assignment, missing audit fields,
  accounting/mutual-exclusion failure, and
  V2l.2 invocation mismatch. Computes:
  - D1 / D2 ON win rates
  - Wilson 95% CI for combined ON rate
  - Paired categories (ON both / OFF both /
    split / invalid)
  - Exact two-sided sign test
  - Exact one-sided regression p
  - Paired bootstrap CI (D1 - D2)
  - Side-collapse diagnostics
  - ON / OFF safety metrics
  - First-divergence per pair
- ``test_doubles_support_move_target_safety_paired.py``
  — 48 tests covering pair merge, side-swap
  matching, outcome normalization, sign test,
  Wilson CI, paired bootstrap determinism,
  malformed/incomplete/duplicate artifact
  handling, corrected wrong-side metric,
  accounting/mutual exclusion, Pollen Puff and
  Skill Swap false-positive guards, first-
  divergence extraction, CLI missing-tag /
  overwrite refusal, and watchdog structure.

### Artifact paths

- ``logs/support_target_paired_phase638c_paired100_*.jsonl``
  (SUPERSEDED — single-file audit bug;
  produced before per-side path fix)
- ``logs/support_target_paired_phase638c_v2.csv``
- ``logs/support_target_paired_phase638c_v2.jsonl``
- ``logs/support_target_paired_phase638c_v2_audit.jsonl``
  (manifest only — per-pair files are
  ``logs/support_target_paired_{NNN}_{ONvOFF|OFFvON}__{p1|p2}.jsonl``)
- ``logs/support_target_paired_phase638c_v2_analysis.json``
- ``logs/support_target_paired_phase638c_v2_analysis.md``

### D1 / D2 (ON-perspective, 100 pairs)

| Arm | ON wins | ON losses | Rate |
|---|---|---|---|
| D1 (ON as p1) | 45 | 55 | 0.450 |
| D2 (ON as p2) | 50 | 50 | 0.500 |
| Combined | 95 | 105 | 0.450 |

Wilson 95% CI for combined ON rate:
[0.356, 0.548].

### Paired categories

- ON both:  18
- OFF both: 23
- Split:    59
- Invalid:  0

### Sign tests

- Decisive pairs (ON both + OFF both): 41
- Two-sided exact p: 0.5327
- One-sided (ON regression) p: 0.2664

### Paired bootstrap (D1 - D2 win rate)

- Point: -0.050
- 95% CI: [-0.200, 0.100]
- n_boot: 2000, seed: 6381

### Side-collapse diagnostics

- D1 rate: 0.450
- D2 rate: 0.500
- |D1 - D2|: 0.050 (OK; under 10pp)

### ON safety metrics (paired audits)

- wrong_side_opportunities: 564
- wrong_side_selected: 0
- wrong_side_avoided: 564
- only_legal: 0
- heal_pulse_into_opponent: 0
- heal_pulse_into_ally: 0
- opponent_disruption_into_ally: 0
- opponent_disruption_into_self: 0
- pollen_puff_candidates: 0
- pollen_puff_blocked: 0
- skill_swap_candidates: 0
- skill_swap_blocked: 0
- spread_count: 340
- focus_fire_count: 540
- accounting_invariant_fail: 0
- mutual_exclusion_fail: 0
- v2l2_invocation_status_mismatch: 0
- v2l2_shared_engine_used_mismatch: 0

### OFF safety metrics (paired audits)

- wrong_side_opportunities: 0
  (feature is OFF; engine skips
  ``support_move_wrong_side_block``)
- spread_count: 388
- focus_fire_count: 523
- accounting_invariant_fail: 0
- mutual_exclusion_fail: 0
- v2l2 mismatches: 0

### First-divergence findings

100 first divergences across 100 pairs:

| Category | Count |
|---|---|
| different_move_kind | 59 |
| different_move | 33 |
| off_side_blocked_only | 3 |
| support_safety_avoided_wrong_side | 4 |
| different_target | 1 |

The majority of divergences are
``different_move_kind`` (one side is switching
or passing while the other moves) or
``different_move`` (both moving, different
choices). 4 cases are real support-safety-caused
divergences where d2 had a blocked candidate
and d1 did not.

### Adoption gates (Phase 6.3.8c)

| Gate | Required | Observed (100 pairs) | Result |
|---|---|---|---|
| All tests pass | True | 1792/1792 OK | PASS |
| Exactly 200 valid battles / 100 complete pairs | 200/100 | 200/100 | PASS |
| Zero timeout/error/no_battle | 0 | 0 | PASS |
| Zero avoidable wrong-side selections in ON | 0 | 0 | PASS |
| Zero Heal Pulse into opponent in ON | 0 | 0 | PASS |
| Pollen Puff blocked = 0 | 0 | 0 | PASS |
| Skill Swap blocked = 0 | 0 | 0 | PASS |
| Accounting and mutual exclusion pass | True | True | PASS |
| V2l.2 runtime audit zero mismatches | 0 | 0 | PASS |
| ON-both >= OFF-both | >= | 18 vs 23 | **FAIL** |
| One-sided exact regression p >= 0.05 | >= 0.05 | 0.2664 | PASS |
| Lower bound of paired bootstrap diff >= -0.02 | >= -0.02 | -0.200 | **FAIL** |
| No suspicious side collapse > 10pp | <= 10pp | 5pp | PASS |
| Spread/focus-fire collapse <= 20% | <= 20% | 12.4% spread, 3.2% focus | PASS |

**Two performance gates fail:**

- ON-both 18 < OFF-both 23.
- Paired bootstrap lower bound -0.20 < -0.02.

### Decision: ADOPTION BLOCKED

The default ``enable_support_move_target_hard_safety``
remains **False**. The production behavior is
correct (zero wrong-side selections, all 564
wrong-side opportunities avoided), and the
correctness gates all pass. The 100-pair paired
qualification provides strong evidence that:

- The feature creates non-zero relevant
  opportunities (564 wrong-side opportunities
  blocked).
- Selected errors are zero (no wrong-side
  Heal Pulse into opponent, no Taunt into ally).
- Side collapse is small (5pp).
- Spread / focus-fire do not collapse.

But the **paired performance gates fail**:

- ON wins fewer decisive pairs than OFF
  (18 vs 23).
- The 95% lower bound of the paired
  bootstrap performance difference is -20pp,
  well below the -2pp limit.

The feature has a real (but small) performance
cost in random doubles: avoiding Thunder Wave
into ally, Taunt into ally, Encore into ally,
etc. sometimes forces the engine to pick a
weaker alternative move. With 100 pairs, the
CI for the paired difference is still wide
([-0.20, 0.10]), so the true effect could be
between -20pp and +10pp. We cannot adopt
under the current -2pp lower-bound gate.

To adopt, a future phase would need to either
(a) reduce avoidance aggressiveness (e.g.
limit to Heal Pulse only), (b) improve the
score penalty for the alternative move picked
when a wrong-side is blocked, or (c) widen
the gate to accept the trade-off under a
separate adoption authorization.

No new policy / evaluator / weight / default
change. ``enable_support_move_target_hard_safety``
remains **False**. Phase V3 remains **BLOCKED**.

## Phase 6.3.8c.1 — Correct paired statistics
(2026-06-14)

**Status: ADOPTION BLOCKED.** The Phase 6.3.8c
statistical analysis had two errors. This section
documents the corrected statistics.

### Errors in 6.3.8c

1. **Combined ON rate used wrong denominator.**
   The 6.3.8c analyzer reported 0.450 (45.0%) as
   the combined ON win rate. The correct value
   is 95/200 = **0.475 (47.5%)** because the
   denominator is 200 battles (D1 + D2), not
   100 pairs.
2. **Paired bootstrap CI used the wrong
   statistic.** The 6.3.8c analyzer reported a
   bootstrap CI of `D1 - D2` win rate (a
   side-position diagnostic), not the mean
   paired treatment effect. The D1-D2 difference
   is a side-effect diagnostic, not the
   ON-vs-OFF treatment effect, and MUST NOT be
   used for the adoption gate.

### Methodology (Phase 6.3.8c.1)

For each complete pair (D1 + D2):

- If ON won both D1 and D2 (ON_both):
  treatment score = +1
- If split (one of D1/D2 ON won):
  treatment score = 0
- If OFF won both D1 and D2 (OFF_both):
  treatment score = -1

Mean paired treatment effect = sum(scores) /
n_pairs. For 18/23/59: `(18 - 23) / 100 = -0.05`.

Paired bootstrap: resample N=100 pairs WITH
replacement (NOT 200 battles independently),
compute the mean of the resampled scores.
Iterations: 2000, deterministic seed: 6381.

Adoption lower-bound gate reads the 95% lower
bound of THIS bootstrap CI.

### D1 / D2 side-position diagnostic (NOT
treatment effect)

- D1 (ON as p1): 45/100 = 0.450
- D2 (ON as p2): 50/100 = 0.500
- D1 - D2: -0.05 (5pp; under 10pp)
- D1 - D2 bootstrap 95% CI: [-0.20, 0.10]

The D1-D2 difference is a side-position
diagnostic only. It is NOT used for the
adoption gate.

### Aggregated ON win rate

- Combined ON wins: 95/200 = 0.475
- Wilson 95% CI (n=200, s=95): [0.407, 0.544]

### Paired categories

- ON both:  18
- OFF both: 23
- Split:    59
- Invalid:  0
- Decisive pairs: 41

### Paired treatment effect

- Mean treatment effect: -0.05
- Paired bootstrap 95% CI: [-0.17, 0.08]
- Adoption lower-bound gate: boot_lo = -0.17

### Sign tests

- Test statistic: k = ON_both = 18
- Decisive pairs: 41
- H0: P(pair is ON-both) = 0.5
- H1 two-sided: P(pair is ON-both) ≠ 0.5
- H1 one-sided (ON regression):
  P(pair is ON-both) < 0.5
- Two-sided exact p: 0.5327
- One-sided (ON regression) p: 0.2664

### Adoption gates (Phase 6.3.8c.1)

| Gate | Required | Observed | Result |
|---|---|---|---|
| All tests pass | True | 1811/1811 OK | PASS |
| 200 valid battles / 100 complete pairs | 200/100 | 200/100 | PASS |
| Zero timeout/error/no_battle | 0 | 0 | PASS |
| Zero wrong-side selections in ON | 0 | 0 | PASS |
| Zero Heal Pulse into opponent in ON | 0 | 0 | PASS |
| Pollen Puff blocked = 0 | 0 | 0 | PASS |
| Skill Swap blocked = 0 | 0 | 0 | PASS |
| Accounting and mutual exclusion pass | True | True | PASS |
| V2l.2 runtime audit zero mismatches | 0 | 0 | PASS |
| **ON-both >= OFF-both** | >= | 18 vs 23 | **FAIL** |
| One-sided exact regression p >= 0.05 | >= 0.05 | 0.2664 | PASS |
| **Lower bound of paired bootstrap treatment effect >= -0.02** | >= -0.02 | -0.17 | **FAIL** |
| Side collapse (D1-D2) <= 10pp | <= 10pp | 5pp | PASS |
| Spread/focus-fire collapse <= 20% | <= 20% | 12.4% spread, 3.2% focus | PASS |

**Two performance gates still fail** even with
the corrected statistics:

- ON-both 18 < OFF-both 23 (a single
  observation, not a paired estimate).
- Paired bootstrap lower bound -0.17 < -0.02.

The one-sided exact regression p-value is 0.2664
(above 0.05 — no statistically significant
regression), but the bootstrap lower bound
remains below the -2pp limit.

### Artifacts

- ``logs/support_target_paired_phase638c1_analysis.json``
  — corrected paired analysis (Phase 6.3.8c.1).
- ``logs/support_target_paired_phase638c1_analysis.md``
  — corrected paired analysis (Phase 6.3.8c.1).
- ``logs/support_target_paired_phase638c_v2_analysis_SUPERSEDED_BY_phase638c1.{{json,md}}``
  — preserved 6.3.8c analysis (renamed to
  indicate supersession).
- Input artifact (unchanged):
  ``logs/support_target_paired_phase638c_v2.jsonl``.

### Decision: ADOPTION BLOCKED

The default ``enable_support_move_target_hard_safety``
remains **False**. Even with the corrected
statistics, the adoption gates fail:

- ON-both 18 < OFF-both 23.
- Paired bootstrap lower bound -0.17 < -0.02.

The CI for the paired treatment effect is
[-0.17, 0.08]. The 95% upper bound is +0.08 (no
regression), but the lower bound -0.17 is
below the -0.02 limit. We cannot adopt under
the current gate.

To adopt, a future phase would need to either
(a) reduce avoidance aggressiveness (e.g.
limit to Heal Pulse only), (b) improve the
score penalty for the alternative move picked
when a wrong-side is blocked, or (c) widen
the gate to accept the trade-off under a
separate adoption authorization.

No new policy / evaluator / weight / default
change. ``enable_support_move_target_hard_safety``
remains **False**. Phase V3 remains **BLOCKED**.

## Phase 6.3.8c.2 — Final Artifact Audit and
Worktree Consolidation (2026-06-14)

**Status: ADOPTION BLOCKED.** No new battles
were run, no localhost was used, and no
production behavior was changed. This phase
re-audits the artifacts produced by Phase
6.3.8c and consolidates the worktree for
Codex review.

### Statistical source of truth

Phase 6.3.8c.1 (not 6.3.8c) is the statistical
source of truth:

- 100 complete pairs.
- 200 valid battles.
- Combined ON wins: 95/200 = 0.475
  (Wilson 95% CI [0.407, 0.544]).
- Paired categories: ON both 18,
  OFF both 23, Split 59, Decisive 41.
- Paired treatment effect: -0.05
  (95% CI [-0.17, 0.08]).
- D1 - D2 is a side-position diagnostic
  only, not a treatment effect.

The Phase 6.3.8c analysis was superseded by
6.3.8c.1 and the artifacts renamed
accordingly
(``..._SUPERSEDED_BY_phase638c1.{json,md}``).

### Real `git status` output (tracked + untracked)

```text
$ git status --short
 M CURRENT_STATE.md
 M ability_rules.py
 M analyze_doubles_decision_audit.py
 M bot_doubles_damage_aware.py
 M bot_doubles_support_move_target_safety_smoke.py
 M bot_vgc2026_phaseV2c.py
 M doubles_decision_audit_logger.py
 M team_preview_policy.py
 M test_doubles_ability_hard_safety.py
 M test_doubles_known_absorb_hard_safety.py
 M test_doubles_support_move_target_safety.py
 M vgc2026_common_plan_evaluator.py
 M vgc2026_matchup_evaluator_v2.py
 M vgc2026_plan_features.py
 M walkthrough.md
?? analyze_doubles_support_move_target_safety_paired.py
?? analyze_vgc2026_phaseV2j_lead_matchups.py
?? analyze_vgc2026_phaseV2k_lead_matchups.py
?? bot_doubles_support_move_target_safety_paired_qualification.py
?? doubles_mechanics.py
?? inspect_vgc2026_phaseV2j_lead_matchup.py
?? inspect_vgc2026_phaseV2k_lead_matchup.py
?? inspect_vgc2026_runtime_parity.py
?? scripts/
?? test_doubles_mechanics_parity.py
?? test_doubles_support_move_target_safety_paired.py
?? test_v2k1_integration.py
?? test_v2k2_regression.py
...
```

Phase 6.3.8c.2 modified files (this phase):

- ``analyze_doubles_support_move_target_safety_paired.py``
  (added inventory helpers and audit CLI)
- ``test_doubles_support_move_target_safety_paired.py``
  (added 20 audit tests)
- ``CURRENT_STATE.md`` (this section)
- ``walkthrough.md`` (this section)

Untracked new files (Phase 6.3.8c lineage):
- ``analyze_doubles_support_move_target_safety_paired.py``
- ``bot_doubles_support_move_target_safety_paired_qualification.py``
- ``test_doubles_support_move_target_safety_paired.py``

Unrelated pre-existing dirty work (NOT
touched by Phase 6.3.8c or 6.3.8c.2):
- ``ability_rules.py``, ``bot_doubles_damage_aware.py``,
  ``bot_doubles_support_move_target_safety_smoke.py``,
  ``bot_vgc2026_phaseV2c.py``,
  ``doubles_decision_audit_logger.py``,
  ``team_preview_policy.py``,
  ``test_doubles_ability_hard_safety.py``,
  ``test_doubles_known_absorb_hard_safety.py``,
  ``test_doubles_support_move_target_safety.py``,
  ``vgc2026_common_plan_evaluator.py``,
  ``vgc2026_matchup_evaluator_v2.py``,
  ``vgc2026_plan_features.py``,
  ``analyze_doubles_decision_audit.py``,
  ``analyze_vgc2026_phaseV2j_lead_matchups.py``,
  ``analyze_vgc2026_phaseV2k_lead_matchups.py``,
  ``doubles_mechanics.py``,
  ``inspect_vgc2026_phaseV2j_lead_matchup.py``,
  ``inspect_vgc2026_phaseV2k_lead_matchup.py``,
  ``inspect_vgc2026_runtime_parity.py``,
  ``scripts/``,
  ``test_doubles_mechanics_parity.py``,
  ``test_v2k1_integration.py``,
  ``test_v2k2_regression.py``,
  ``test_v2k3_regression.py``,
  ``test_v2k4_regression.py``,
  ``test_v2k5_regression.py``,
  ``test_vgc2026_phaseV2j.py``,
  ``test_vgc2026_phaseV2k.py``,
  ``test_vgc2026_runtime_engine_parity.py``,
  ``vgc2026_lead_matchup_evaluator_v3.py``.

These are V2k.x and V2l.1 work from prior
phases and are preserved per AGENTS.md
"Preserve User Work".

### Real artifact inventory

The qualifier produced (per filesystem):

- **400 per-side audit files** total,
  distributed:
  - 100 files: ``support_target_paired_{NNN}_ONvOFF__p1.jsonl``
  - 100 files: ``support_target_paired_{NNN}_ONvOFF__p2.jsonl``
  - 100 files: ``support_target_paired_{NNN}_OFFvON__p1.jsonl``
  - 100 files: ``support_target_paired_{NNN}_OFFvON__p2.jsonl``
- Each pair has 4 per-side files (D1.p1,
  D1.p2, D2.p1, D2.p2 — one for each engine
  in each side-swap arm).
- 4 files × 100 pairs = 400 total.
- **200 ON-side audits** (ONvOFF.p1 from D1
  + OFFvON.p2 from D2).
- **200 OFF-side audits** (ONvOFF.p2 from D1
  + OFFvON.p1 from D2).

Input artifacts (preserved, unchanged):

- ``logs/support_target_paired_phase638c_v2.csv`` —
  26,438 bytes, sha256
  ``cdfbc93679a7f4e813e99056cd37f24c4cbb8e6caacf0df272668ea22c578f82``
- ``logs/support_target_paired_phase638c_v2.jsonl`` —
  110,454 bytes, sha256
  ``8485da234c3e3dc30a03148ef004f59ffce6a69f254e31ca40625f8d9219a965``,
  200 battle records
- ``logs/support_target_paired_phase638c_v2_audit.jsonl``
  — 0 bytes (manifest was never written; the
  per-side files are the real artifacts).
- 400 per-side files, total 152,666,709 bytes
  (~149 KB).

### 200 vs 400 per-side file discrepancy

Both counts are correct in different
contexts:

- **400** = total per-side audit files
  on the filesystem
  (4 per pair × 100 pairs).
- **200** = per-arm per-side files
  (200 ON + 200 OFF).
- **200** = total battles
  (100 pairs × 2 side-swap arms).

The Phase 6.3.8c.1 report said "200 battles,
all ON-side audits" which is correct: 200
ON-side audit files were the basis for the
ON metrics (and 200 OFF-side files for the
OFF metrics). The "400" figure is the
filesystem total.

### Files changed in Phase 6.3.8c.2

- ``analyze_doubles_support_move_target_safety_paired.py``
  — added:
  - ``_parse_audit_filename`` (filename parser)
  - ``inventory_artifacts`` (pure helper)
  - ``sha256_file`` (file digest)
  - ``file_metadata`` (size/mtime/sha256)
  - ``format_git_status_lines`` (formatter that
    cannot double-classify)
  - ``write_artifact_audit`` (writes JSON +
    Markdown audit report)
  - ``--audit-only`` and ``--audit-tag`` CLI
    flags
- ``test_doubles_support_move_target_safety_paired.py``
  — added 20 tests in ``TestArtifactAudit638c2``
- ``CURRENT_STATE.md`` and ``walkthrough.md``
  (this section)

### Generated audit artifacts (Phase 6.3.8c.2)

- ``logs/support_target_paired_phase638c2_artifact_audit.json``
- ``logs/support_target_paired_phase638c2_artifact_audit.md``

### Verification

- ``test_doubles_support_move_target_safety_paired``:
  87 tests, OK, 6.496s
- ``test_doubles_support_move_target_safety``:
  82 tests, OK
- ``test_vgc2026_runtime_engine_parity``:
  54 tests, OK
- Full discovery with
  ``-W error::ResourceWarning``:
  1831 tests, OK, EXIT=0, 190.085s
- ``py_compile``: clean
- ``git diff --check``: clean

### Decision: ADOPTION BLOCKED

The default ``enable_support_move_target_hard_safety``
remains **False**. The corrected statistics
from 6.3.8c.1 are still the source of truth.
This 6.3.8c.2 phase only audited artifacts
and consolidated documentation — no new
battles, no behavior change, no default
change. Phase V3 remains **BLOCKED**.

### Worktree status

Working tree is dirty but documented.
Ready for Codex review.

- Phase 6.3.8c lineage (qualifier, analyzer,
  test, audit, docs) is isolated and reviewable
  in this branch.
- Unrelated V2k.x and V2l.1 dirty work is
  preserved per AGENTS.md.
- No commit, no push.

## Phase 6.3.8c.3 — Dependency-Aware Commit
Boundary Audit (2026-06-14)

**Status: ADOPTION BLOCKED.** No new battles
were run, no localhost was used, and no
production behavior was changed. This phase
documents the dependency-correct commit
boundary plan for the dirty worktree.

### Manifest classification (the 0-byte file)

`logs/support_target_paired_phase638c_v2_audit.jsonl`
is **0 bytes** and is classified as
`optional_expected_empty` (not a failure).

The qualifier (`bot_doubles_support_move_target_safety_paired_qualification.py`):

1. Declares the manifest path in
   ``init_artifacts()``.
2. Truncates the file to 0 bytes in
   ``init_artifacts()``.
3. Never writes to the file.

The analyzer reads the file only for file
metadata (size + sha256), not as a data
source. The per-side audit files (400 total)
are the real artifacts.

This is a **creation defect** (file is
created at 0 bytes but never written to) but
NOT a hard-fail. The 0-byte state is
documented as `optional_expected_empty`.

### Commit groups (10 groups, in order)

| Group | Files | Tests | Depends on |
|---|---|---|---|
| 1. V2k.x mechanics foundation | `doubles_mechanics.py` | py_compile | (none) |
| 2. V2k.x evaluators + team_preview + parity | 6 files (incl. `test_doubles_mechanics_parity`) | 62 tests | Group 1 |
| 3. V2k.x VGC player + V2l.1 analyzers/inspectors/scripts | 7 files | py_compile + import | Groups 1, 2 |
| 4. 6.3.8b production: engine + logger + analyzer | 3 files | py_compile + import | Group 1 |
| 5. 6.3.8b ability hard safety | 3 files (incl. tests) | 114 tests | (none) |
| 6. 6.3.8b support target safety (smoke + test) | 2 files | 82 tests | Groups 4, 5 |
| 7. 6.3.8c paired lineage (qualifier + analyzer + test) | 3 files | 92 tests | Group 4 |
| 8. V2k.x regression tests | 5 files | 5 modules | Groups 1, 2, 3 |
| 9. V2l.1 VGC parity tests | 3 files | 54 parity tests | Groups 1, 2, 3, 4 |
| 10. Documentation: CURRENT_STATE.md + walkthrough.md (FINAL) | 2 files | n/a | Groups 1-9 |

### Clean-base simulation

All 10 groups compile and import cleanly in
clean-base simulation. Per-module tests
pass in both clean and production
environments. The discovery path fails in
the clean worktree due to a Python
module-cache pollution issue (test files
exist in both production and worktree
paths) — this is not a code issue.

### Generated artifact policy

- `logs/` is gitignored (`.gitignore` line 13).
- No `logs/` files are tracked.
- Generated artifacts must NEVER be staged.
- The 6.3.8c.3 commit boundary audit
  (`commit_boundary_audit_phase638c3.{json,md}`)
  is placed in **repo root** (not in `logs/`),
  so it can be staged for future commits.

### Blockers before commit

1. (none for code groups)
2. V2k.x / V2l.1 prereq: Groups 1, 2, 3, 8, 9
   must be committed first (or kept dirty).
3. Documentation (Group 10) is FINAL.
4. Production behavior unchanged.
5. No commit authorization given.

### Verification

- `test_doubles_support_move_target_safety_paired`:
  92 tests, OK, 9.833s
- Production full discovery:
  1836 tests, OK, EXIT=0, 258.135s
- `py_compile`: clean (3 files)
- `git diff --check`: clean
- Clean-base simulation per-group: all OK

### No battle / server / API confirmation

- No new battles run
- No localhost used (task said ไม่ต้องใช้ localhost)
- No official Showdown connection
- No online API, no LLM, no scrape, no browser

### Defaults / fingerprint / adoption status unchanged

- `enable_support_move_target_hard_safety` = False
- `enable_ability_hard_safety_only` = True
- V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
  (unchanged)
- Phase V3 = BLOCKED (unchanged)

### Worktree status: ready for commit?

**NOT YET READY for commit** because:
1. V2k.x and V2l.1 work is mixed with 6.3.8c work.
2. Documentation covers all 5 sub-phases and cannot
   be cleanly split.
3. `bot_doubles_damage_aware.py` (Group 4) is mixed
   (V2k + 6.3.8b).
4. Generated artifacts in `logs/` must not be staged.
5. No commit authorization from the user.

Stopping for Codex review.

## Phase 6.3.8c.4 — Commit Boundary Repair (2026-06-15)

**Status: VERIFIED; ADOPTION BLOCKED.** This section supersedes the
Phase 6.3.8c.3 commit-boundary plan.

### Repairs

- The paired qualifier no longer creates the unused aggregate
  `*_audit.jsonl` placeholder. Historical zero-byte manifests are
  preserved and classified as `legacy_empty_creation_defect`.
- Current runs expect no aggregate manifest; the 400 per-side JSONL
  files remain the authoritative runtime-audit evidence.
- Hardcoded checkout paths were removed from affected VGC tools and
  tests. Subprocesses and fixtures now resolve from `__file__`.
- Tests that depended on ignored `logs/` fixtures now generate
  temporary fixtures or explicitly verify missing-artifact failure.
- The obsolete `commit_boundary_audit_phase638c3.{json,md}` reports
  were replaced by `commit_boundary_audit_phase638c4.{json,md}`.

### Verified commit groups

| Group | Scope | Clean-check result |
|---|---|---|
| 1 | Checkout-local path and test isolation | 569 tests, OK |
| 2 | Canonical mechanics, VGC runtime, and support-target stack | 624 tests, OK |
| 3 | 6.3.8c paired qualifier, analyzer, and tests | 93 tests, OK |
| 4 | Documentation and boundary reports | Static validation |

Each group was copied in order onto a clean `git archive HEAD`
checkout. Final clean-check discovery ran **1837 tests in 180.19s,
EXIT=0**, with zero skips. Production-tree discovery ran **1837 tests
in 186.06s, EXIT=0**.

### Commit readiness

The source tree is ready for ordered commits using the exact file
lists in `commit_boundary_audit_phase638c4.json`. Generated files
under `logs/` remain ignored and must not be staged. No commit or push
was performed.

### Unchanged decisions

- `enable_support_move_target_hard_safety = False`
- Support-target safety adoption remains **BLOCKED**
- Phase V3 remains **BLOCKED**
- No battle, server, online API, scrape, or hidden-information access
  was used in this repair
