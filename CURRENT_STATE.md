# Current Project State

Last verified: 2026-06-13 08:53 (Asia/Bangkok)

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

The repository-wide discovery run completed 1,274 tests but is not
green: 10 errors and 5 failures remain in
`test_doubles_dynamic_move_type_safety.py` because expected dynamic
absorb fields are absent from logger output. V2i does not modify the
doubles player, logger, analyzer, or those tests; the focused and
cross-phase VGC suites above are green. The dynamic-type regression
must be handled as a separate doubles correctness task.

Artifacts:

- `logs/vgc2026_phaseV2i_matchup_evaluator.json`
- `logs/vgc2026_phaseV2i_matchup_evaluator.md`

No battle was run. Outcome labels were loaded only after evaluator
configuration freeze. The final fingerprint is
`c86d75271f833ede664b756c717dd4ce1c9c6791505c5c32d1864101ebfaa22a`.
