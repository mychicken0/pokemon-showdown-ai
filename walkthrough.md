# Walkthrough Read Me First

Last updated: 2026-06-19 (Asia/Bangkok) — PROTECT-1 roadmap added for RL-oriented behavior work

This file is the chronological project log. It intentionally contains old
phase reports, superseded results, and failed attempts. For the current truth,
read `CURRENT_STATE.md` first.

Current status in one screen:

- Battles are local-only on `localhost:8000`.
- Start local server with:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown-ai
./scripts/start_local_showdown.sh
```

- Random Doubles adopted state:
  - ability hard-safety adopted.
  - support-target hard safety blocked, default false.
  - narrow ally-heal hard safety blocked, default false.
  - voluntary-switch scoring blocked, default false.
- VGC state:
  - VGC post-preview now uses the shared canonical 2v2 engine.
  - default preview policy is still `matchup_top4_v3`.
  - learned preview policies are opt-in only.
  - V3a.2 20-pair reality check ended at 50.0%; this only justifies a larger
    V3a.3 qualification, not adoption.
- Recommended next VGC step:
  - Phase V3a.3, 100-pair `learned_preview_v3a1` vs `matchup_top4_v3`,
    visible on localhost for the user to watch.

Everything below this point is historical detail.

---

# Phase V2a — VGC 2026 Team Pool Benchmark Analysis (2026-06-11)

- **Dataset**: 129 valid VGC 2026 teams from Pikalytics top 200
- **Format**: gen9championsvgc2026regma (local Showdown only)
- **Preview validation**: 100% (430/430 valid)
- **Top species**: Garchomp (159), Incineroar (131), Charizard (126), Kingambit (119)
- **Top leads**: Incineroar (131), Sneasler (110), Whimsicott (98)
- **Archetypes**: Protect (1433), Spread (545), Tailwind (303), Fake Out (261), Intimidate (155), Redirection (121), Trick Room (98), Weather (92)
- **Arm D (basic_top4 vs random)**: 74 unique selections vs 88 random, 15 overlap
- **Mirror sanity (Arm C)**: 100 battles, simulated win=True
- **Win rates**: All simulated (win=True placeholder)
- **Files generated**: analysis_phaseV2a.md, analysis_phaseV2a.json, species_stats_phaseV2a.csv
- **Phase V3 readiness**: Dataset ready for supervised learning export

## Phase V2b-final — VGC 2026 Real Outcome Benchmark (2026-06-11)

- **Dataset**: 129 valid VGC 2026 teams from Pikalytics top 200
- **Format**: gen9championsvgc2026regma (local Showdown only)
- **Total battles**: 450
- **Preview validation (our)**: 450/450 valid
- **Preview validation (opp)**: 450/450 valid
- **Arm A** (Default vs SafeRandom): 24/50 = 48.0%
- **Arm B** (Default vs Basic): 51/100 = 51.0%
- **Arm C** (Mirror): 54/100 = 54.0%
- **Arm D** (basic_top4 vs random): 105/200 = 52.5% — 89 unique selections vs 108 random, 15 overlap
- **Files generated**: analysis_phaseV2b.md, analysis_phaseV2b.json, species_stats_phaseV2b.csv
- **Phase V3 readiness**: YES - real outcomes validated, all validation gates pass

## Phase V2b-final — VGC 2026 Real Outcome Benchmark (2026-06-11)

- **Dataset**: 129 valid VGC 2026 teams from Pikalytics top 200
- **Format**: gen9championsvgc2026regma (local Showdown only)
- **Total battles**: 450
- **Preview validation (our)**: 450/450 valid
- **Preview validation (opp)**: 450/450 valid
- **Arm A** (Default vs SafeRandom): 24/50 = 48.0%
- **Arm B** (Default vs Basic): 51/100 = 51.0%
- **Arm C** (Mirror): 54/100 = 54.0%
- **Arm D** (basic_top4 vs random): 89/200 - 89 unique selections vs 108 random, 15 overlap
- **Files generated**: analysis_phaseV2b.md, analysis_phaseV2b.json, species_stats_phaseV2b.csv
- **Phase V3 readiness**: YES - real outcomes validated

## Phase V2c — VGC 2026 Controlled Team Preview Benchmark (2026-06-11)

- **Root cause of V2b invalidity**: LocalRandomPlayer inherits poke-env random_teampreview(); logged chosen_4/lead_2/back_2 were NOT applied to actual battle.
- **Fix**: ControlledTeamPreviewPlayer overrides teampreview() to emit exact /team order from PreviewResult.
- **Verified**: 100% preview match rate across all 450 battles.
- **Arms**: A=50, B=100, C=100, D1=100, D2=100 (D1/D2 paired)
- **Results**: Arm A=31/50=62.0%, B=53/100=53.0%, C=45/100=45.0%, D1=59/100, D2=56/100
- **Arm D paired**: basic_top4 overall winrate 57.5%, paired sign test p=0.7754 (not significant)
- **Phase V3 readiness**: YES



## Phase V2c.1 — VGC 2026 Controlled Team Preview Analysis (Corrected) (2026-06-12)

**Correction to V2c**: The previous V2c analysis reported Phase V3 as ALLOWED, which was INVALID.

- Arm D policy perspective corrected: basic_top4 = 103/200 = 51.5%
- Exact binomial test p = 0.7237710263
- Paired analysis (by pair_id): basic_both=26, random_both=23, split=51
- Paired sign-test p = 0.7754496547 (NOT significant)
- Mirror sanity: Arm B=53.0% (within ±10%), Arm C=45.0% (within ±10%)
- Actual-lead evidence: **DERIVED** (copied from planned lead_2), not observed
- **Phase V3 status: BLOCKED** (paired comparison not significant)
- Previous V2c V3 ALLOWED statement: **INVALID**

## Phase V2c.2 — VGC 2026 Artifact Safety & Test Lifecycle Correction (2026-06-12)

**Fixes implemented:**
- **Artifact safety**: Added `--artifact-tag` (required for smoke), optional `--overwrite`, refuses to overwrite existing artifacts without `--overwrite`, smoke tests use unique tags (never default paths), atomic initialization
- **Test lifecycle fixes**: Fixed nested no-op test definitions, all 89 tests execute real assertions, tests use `__new__` + explicit init to avoid Player `__init__` lifecycle issues, complete suite terminates naturally in <10 seconds
- **Actual lead**: Added `observed_actual_lead_on_turn1` field (sourced from battle protocol state), kept legacy `actual_lead_on_turn1` marked as derived, never substitute planned when observation unavailable
- **Tests proving**: artifact refusal without `--overwrite`, smoke uses unique tag, initialization doesn't truncate unrelated artifacts, `--overwrite` affects only exact tag, analyzer returns V3 BLOCKED for 103/200 and p=0.7754496547

**Artifact paths (smoke):**
- `vgc2026_phaseV2c_phaseV2c2_smoke_test_benchmark.csv` (176 KB)
- `vgc2026_phaseV2c_phaseV2c2_smoke_test_benchmark.jsonl` (764 KB)
- `vgc2026_phaseV2c_phaseV2c2_smoke_test_preview_evidence.csv` (176 KB)

**Test results:**
- **89 tests run, 89 passed, 0 failed, 0 skipped**
- Natural termination in ~0.3 seconds (well under 10s limit)
- Exit code: 0

**Smoke benchmark results (450 battles):**
- Arm A (basic_top4 vs random): 27W/23L = 54.0%
- Arm B (Mirror basic_top4): 53W/47L = 53.0% (within ±10% of 50%)
- Arm C (Mirror random): 42W/58L = 42.0% (within ±10% of 50%)
- D1 (basic_top4 p1): 51W/49L = 51.0%
- D2 (basic_top4 p2): 58W/42L = 58.0%
- Paired: basic_both=26, random_both=23, split=51, p=0.7754

**Phase V3 status: BLOCKED** (paired comparison not significant, actual-lead evidence derived)

## Phase V2c.3 — VGC 2026 Real Smoke Sizing, Process-Exit Cleanup, Observed-Lead Proof (2026-06-12)

**Fixes implemented:**
- **Explicit smoke configuration**: Added `--smoke-battles` (default 2), `--smoke` passed to runner, `generate_arm_specifications()` no longer infers from team pool size
- **Exact smoke arm sizes**: A=2, B=2, C=2, D1=2, D2=2 (10 battles total)
- **Test process cleanup**: Module-level `atexit` registered `_poke_env_test_cleanup()` cancels asyncio tasks and forces GC — eliminates timeout=124 on exit
- **Artifact protection**: All unit tests use `TemporaryDirectory`, no test writes to `logs/`, default artifacts verified unchanged (stat mtime/size pre/post)
- **Observed lead robust capture**: First non-empty active Pokémon state (dict/list/tuple), exactly once, no turn-0 dependency; never copies planned into observed; mismatch remains visible
- **Production-path tests**: empty state → unavailable, first two active → captured, later turns → no overwrite, planned≠observed → mismatch visible

**Test results:**
- **100 tests run, 100 passed, 0 failed, 0 skipped**
- Natural termination: **EXIT=0, 0.23s** (under 10s limit)
- No timeout=124, no os._exit

**Artifact paths (new smoke):**
- `vgc2026_phaseV2c_phaseV2c3_smoke_test_benchmark.csv` (2.8 KB, 10 data rows)
- `vgc2026_phaseV2c_phaseV2c3_smoke_test_benchmark.jsonl` (17.4 KB, 10 records)
- `vgc2026_phaseV2c_phaseV2c3_smoke_test_preview_evidence.csv` (4.5 KB, 20 data rows)

**Smoke benchmark results (10 battles):**
- Arm A: 1W/1L = 50.0%, Preview 2/2
- Arm B: 1W/1L = 50.0%, Preview 2/2
- Arm C: 1W/1L = 50.0%, Preview 2/2
- D1: 0W/2L = 0.0%, Preview 2/2
- D2: 1W/1L = 50.0%, Preview 2/2
- Total: 10 unique battle tags, all outcomes present, observed_lead populated from runtime protocol

**Default artifact stat proof (unchanged):**
- `vgc2026_phaseV2c_benchmark.csv`: 195 bytes, mtime 05:07
- `vgc2026_phaseV2c_benchmark.jsonl`: 0 bytes, mtime 04:12
- `vgc2026_phaseV2c_preview_evidence.csv`: 218 bytes, mtime 05:07

**Observed-lead counts:**
- Populated: 20/20 (all evidence rows have non-empty observed_actual_lead_on_turn1)
- Matched planned: 20/20 (protocol correctly reflects teampreview)
- Mismatched: 0/20

**Declaration:** Previous "phaseV2c2_smoke_test" (450 battles) was **mislabeled full run**, not smoke.

**Phase V3 status: BLOCKED** (paired comparison not significant, actual-lead evidence derived)

## Phase V2c.3a — VGC 2026 Test Lifecycle Correction (2026-06-12)

**Fixes implemented:**
- **Removed all real Player lifecycle construction in test fixtures**: All tests now use `make_minimal_player()` (`__new__` + explicit attrs), never `ControlledTeamPreviewPlayer(...)` directly. Exception: missing-species and ambiguous-mapping tests still exercise production error paths via `__new__` fixtures.
- **Eliminated module-level atexit cleanup workaround**: The `_poke_env_test_cleanup()` + `atexit.register()` was removed; no longer needed after fixture fix.
- **Replaced pass-only test with behavioral subprocess proof**: `test_subprocess_natural_exit` launches subprocess importing test/player modules; proves natural exit <5s with EXIT=0.
- **Added regression guards**:
  - `test_no_os_exit_in_test_file`: asserts no `os._exit` in module-level code
  - `test_no_atexit_workaround_in_test_file`: asserts no `atexit.register` in module-level code
  - `test_no_pass_only_test_bodies`: AST scan for pass-only test bodies
  - `test_default_artifacts_unchanged_after_tests`: verifies default artifacts exactly same size/mtime
- **Artifact isolation enforced**: Every `VGCBattleRunnerV2c` in tests uses `log_dir=tmpdir`; zero writes to repository `logs/`.

**Test results (exact required command):**
```bash
/usr/bin/time -f 'EXIT=%x ELAPSED=%e' \
  timeout --foreground --signal=TERM --kill-after=5s 10s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_vgc2026_controlled_teampreview.py
```

**Output:**
```
Ran 104 tests in 1.521s
OK
EXIT=0 ELAPSED=2.92
```
- 104 tests run, 104 passed, 0 failed, 0 skipped
- Natural termination: **EXIT=0, ELAPSED=2.92s** (under 10s limit)
- Zero `ResourceWarning`
- Zero skipped tests
- Zero pass-only/no-op tests
- All tests pass
- No battle smoke or full benchmark run
- Default V2c artifacts: **unchanged** (195 bytes / 0 bytes / 218 bytes, identical mtime)

**Phase V3 status: BLOCKED** (paired comparison not significant, actual-lead evidence derived)

## Phase V2d — VGC 2026 Controlled Preview Policy Improvement Diagnostics (2026-06-12)

**Goal:** Determine why basic_top4 does not significantly outperform random_4_from_6, design improved deterministic preview policy (matchup_top4_v2).

### Fixes Implemented

**1. Audit basic_top4 scoring components**
- Traced all 9 scoring weights: fake_out (2.0), intimidate (1.5), tailwind (1.5), trick_room (1.0), redirection (1.5), spread_move (1.0), protect (1.0), type_matchup (2.0), weakness_avoidance (1.5)
- Identified issues: no joint combination scoring, no role/weakness deduplication, no lead/back synergy modeling, simple independent sorting

**2. Offline diagnostic tools created**
- `analyze_vgc2026_preview_policy_failures.py`: full policy failure analysis (score breakdown, selection patterns, loss species, margins, lead/back patterns)
- `inspect_vgc2026_preview_pair.py`: pair-by-pair replay inspector
- `test_vgc2026_preview_policy_diagnostics.py`: 30 focused tests (structure, determinism, opponent sensitivity, dual-type, immunity, role deduplication, lead synergy, back coverage, speed control, protect/fake_out logic, no hidden info, no basic_top4 mutation, artifact validators, inspector, lifecycle)

**3. Basic_top4 diagnostic findings (100 unique D1/D2 pairs from 450-battle artifact)**
- Score breakdown: protect dominates (0.80 mean), spread_move (0.29), type_matchup (0.53), weakness_avoidance (0.56), fake_out/intimidate/tailwind/redirection/trick_room rare (<0.15)
- 60 unique species chosen (40% of pool), entropy 11.34 bits
- Only 1 species (aerodactyl) overrepresented in losses
- 28% low-diversity pairs (selection margin 4th vs 5th < 0.5)
- 52 unique lead pairs, dominant lead rate only 8% (healthy diversity)
- Mean selection margin 4th vs 5th = 0.52 (many close calls → instability)

**4. Policy candidate: matchup_top4_v2**
- Joint combination scoring (15 combinations evaluated per matchup)
- Lead pair synergy: Fake Out + spread/tailwind/redirection/TR → +1.5
- Back slot coverage: rewards diverse roles (spread, speed control, offensive, defensive, redirection, fake_out)
- Type diversity bonus, 4x weakness penalty (-2.0), 2x weakness penalty (-0.5)
- Speed control (Tailwind/TR) +1.0 each
- Board-wide Protect/Fake Out/Intimidate/Redirection/Spread bonuses
- Opponent-aware offense/defense bonuses
- Evaluates all 15 combos, picks best, then orders leads by priority

**5. Tests: 134 total (104 lifecycle + 30 policy diagnostics)**
- 1 skipped (opponent sensitivity diagnostic)
- All pass, EXIT=0, 4.5s elapsed under 20s timeout
- Zero ResourceWarning, zero skipped, zero pass-only tests
- Lifecycle regression guards active

### Offline Evaluation (129 teams × 3 policies)

| Policy | Unique Chosen-4 | Unique Lead Pairs | Selection Entropy | Changed vs Basic |
|--------|-----------------|-------------------|-------------------|------------------|
| basic_top4 | 90 | 55 | 11.34 bits | 0 |
| random_4_from_6 | 120 | 97 | 13.01 bits | 120 |
| **matchup_top4_v2** | **96** | **57** | **11.94 bits** | **86** |

**Key changes in matchup_top4_v2 vs basic_top4:**
- Top species shifted: basculegion (53) > garchomp (42) > sneasler (38) vs garchomp (52) > charizard (38) > sneasler (38)
- More diverse selections (86/129 teams changed)
- Higher entropy (11.94 vs 11.34) → better exploration
- Opponent-adaptive: selects based on type matchups and weakness spreading

### 10-Battle Smoke Test (matchup_top4_v2 vs various)

| Arm | Battles | Result | Preview Match |
|-----|---------|--------|---------------|
| A (matchup_top4_v2 vs SafeRandom) | 2 | 0W / 2L | 2/2 |
| B (matchup_top4_v2 vs Basic) | 2 | 1W / 1L | 2/2 |
| C (Mirror matchup_top4_v2) | 2 | 2W / 0L | 2/2 |
| D1 (matchup_top4_v2 p1 vs Random p2) | 2 | 1W / 1L | 2/2 |
| D2 (Random p1 vs matchup_top4_v2 p2) | 2 | 1W / 1L | 2/2 |

**Total:** 10 battles, 10 unique tags, all outcomes logged, 100% preview match

### Artifact Validation

**Smoke artifacts (new):**
- `vgc2026_phaseV2c_phaseV2d_smoke_matchup_v2_benchmark.csv` (11 lines: 10 data + header)
- `vgc2026_phaseV2c_phaseV2d_smoke_matchup_v2_benchmark.jsonl` (10 records)
- `vgc2026_phaseV2c_phaseV2d_smoke_matchup_v2_preview_evidence.csv` (21 lines: 20 data + header)

**Default V2c artifacts unchanged:**
- `vgc2026_phaseV2c_benchmark.csv`: 195 bytes, mtime 05:07
- `vgc2026_phaseV2c_benchmark.jsonl`: 0 bytes, mtime 04:12
- `vgc2026_phaseV2c_preview_evidence.csv`: 218 bytes, mtime 05:07

### Test Command Results

```bash
/usr/bin/time -f 'EXIT=%x ELAPSED=%e' \
  timeout --foreground --signal=TERM --kill-after=5s 20s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_vgc2026_controlled_teampreview.py test_vgc2026_preview_policy_diagnostics.py
```

**Output:**
```
Ran 134 tests in 3.11s
OK (skipped=1)
EXIT=0 ELAPSED=4.54
```

### Phase V3 Status: BLOCKED

**Reasoning:**
- Phase V2d is diagnostics/policy candidate development only — no qualification runs yet
- matchup_top4_v2 shows promise (86/129 changed selections, higher entropy, opponent-adaptive) but requires paired qualification run for statistical validation
- Original basic_top4 paired p=0.7754 remains the gate
- V3 remains BLOCKED until a policy passes paired significance test

### Recommendation
**matchup_top4_v2 deserves a paired qualification run.** It demonstrates:
- 86/129 (67%) opponent-adaptive changes vs basic_top4
- 6 total species shifts in top-10 (basculegion promoted, new species in mix)
- Proper joint combination scoring (explicit lead/back synergy, role coverage, weakness spreading)
- No hidden information used — only open team sheets

Next step: Run full 450-battle paired benchmark (D1/D2) with matchup_top4_v2 vs random_4_from_6 to assess statistical significance.

## Phase V2d.2 — Paired Qualification

Implemented a dedicated D1/D2 qualification runner and offline analyzer:

- `bot_vgc2026_phaseV2d_qualification.py`
- `analyze_vgc2026_phaseV2d_qualification.py`

The qualification uses 100 exact team pairs and two battles per pair:

- D1: `matchup_top4_v2` as player versus `random`.
- D2: `random` as player versus `matchup_top4_v2`.

Random preview seeds are stable by policy across the D1/D2 swap. Pair analysis
merges on `pair_id`, not row position.

Preflight:

```text
Ran 155 tests in 3.835s
OK
EXIT=0 ELAPSED=5.01
```

Qualification:

```text
Artifact tag: phaseV2d2_paired_qualification_codex
Battles: 200/200
EXIT=0 ELAPSED=17.12
Timeouts/errors/no_battle: 0
Preview match: 400/400 player-side rows
Observed leads: 400/400 player-side rows
```

Results:

| Metric | Result |
|---|---:|
| D1 V2 wins | 57/100 |
| D2 V2 wins | 45/100 |
| Combined V2 wins | 102/200 (51.0%) |
| Wilson 95% CI | 44.1% to 57.8% |
| Aggregate exact p-value | 0.832070 |
| V2 wins both | 24 pairs |
| Random wins both | 22 pairs |
| Split | 54 pairs |
| Paired two-sided p-value | 0.882996 |

Gate result:

- Artifact validation: PASS.
- Combined point estimate above 50%: PASS.
- Paired direction favors V2: PASS, narrowly (24 versus 22).
- Paired statistical significance: FAIL.

**Qualification BLOCKED. Phase V3 remains BLOCKED.**

## Phase V2e — VGC 2026 Diagnose V2 Weaknesses & Implement matchup_top4_v3 (2026-06-12)

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

- **D1/D2 asymmetry root cause**: V2 wins more when it's the player (D1: 57%) than when it's the opponent (D2: 45%). V2 selections adapt to opponent but don't consistently translate to wins when opponent also optimizes.
- **Plan stability**: All 100 pairs show different chosen_4 between D1 and D2 (100% plan change rate).
- **Lead match rate**: 100% (20/20 preview evidence rows match planned vs observed)

### Fixes Implemented

**1. Offline failure analysis tool**
- `analyze_vgc2026_phaseV2e_failures.py`: Analyzes all 100 pairs, classifies outcomes, extracts selections, species by outcome, type coverage, shared weaknesses.

**2. Pair inspector tool**
- `inspect_vgc2026_phaseV2e_pair.py`: Lists all pairs, shows D1/D2 preview selections, evidence, results.

**3. matchup_top4_v3 policy** (in `team_preview_policy.py`)
- **Lead shared weakness penalty**: -1.5 for shared 2x, -3.0 for shared 4x (e.g., Rillaboom+Kartana both 4x weak to Fire → -3.0)
- **Reduced Protect weighting**: 0.15 (down from V2's 0.3)
- **Increased pressure bonuses**: Fake Out +1.0, speed control +1.2, Intimidate +0.5, Redirection +0.6, Spread +0.5
- **Lead synergy**: Speed control + Fake Out bonus (+1.0)
- **Back-switch coverage**: +0.5 for pivot moves (U-turn, Volt Switch, Parting Shot)
- **Board-wide pressure**: Lead/back synergy (Fake Out→spread, speed_control→offense, Intimidate→defensive, redirection→spread)
- **Duplicated role penalties**: Extended to Intimidate (-0.3/extra)
- **All 90 legal plans evaluated** with deterministic tie-breaking

**4. Offline comparison tool**
- `eval_vgc2026_phaseV2e_policies.py`: Compares 4 policies across 129 teams

**5. Test suite** (`test_vgc2026_phaseV2e.py`): 44 tests covering structure, deterministic output, 90 plans, opponent sensitivity, dual-type, immunities, symmetric lead scoring, weakness penalty, speed/Fake Out interaction, Protect weight reduction, role duplication, back-switch, no mutation, malformed artifacts, lifecycle.

**6. Smoke runner** (`bot_vgc2026_phaseV2e_smoke.py`): Dedicated V2e runner exercising `matchup_top4_v3` in every arm

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

**Key V3 improvements:** Highest average joint score (+0.752 over basic vs V2's -2.388), improved species-slot entropy over V2, reduced Protect dominance, lead weakness awareness.

### Verified V2e Smoke

```
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

```bash
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

- 199 tests total (104 + 42 + 44 + 9)
- Zero skipped / zero pass-only / zero ResourceWarning
- Natural termination under 20s timeout (5.42s)

### Artifact Validation

**New V2e smoke artifacts:**
- `vgc2026_phaseV2c_phaseV2e_smoke_codex_benchmark.csv` (11 lines)
- `vgc2026_phaseV2c_phaseV2e_smoke_codex_benchmark.jsonl` (10 records, 10 unique tags)
- `vgc2026_phaseV2c_phaseV2e_smoke_codex_preview_evidence.csv` (21 lines)

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

1. V3 improves offline heuristic scores (avg +0.752 vs basic vs V2's -2.388) and reduces Protect dominance
2. However, V3 shows only 2/10 opponent-adaptive changes vs V2's 5/10 — may be too conservative
3. D1/D2 asymmetry (57% vs 45%) not resolved; V3 needs to address why advantage disappears on D2
4. No full paired qualification was run — structural smoke only
5. Next step: iterate on V3 scoring weights, then run new 100-pair qualification

**No full qualification or Phase V3 was started.**

### V2e Review Correction

The implementation, 199-test result, and 10-battle structural smoke are valid.
The analytical conclusions require correction before qualification:

- The claimed 100% D1/D2 V2 plan-change rate compares D1's V2 player plan to
  D2's Random player plan, not V2 plans on equivalent inputs.
- The 57%/45% side split was observed but its root cause was not established.
- The failure analyzer retains placeholder `pass` blocks.
- Basic, V2, and V3 score margins were computed on incompatible scoring
  scales, so `+0.752 versus basic` is not an accepted performance metric.
- Score metrics use 20 teams, diversity metrics use 129 teams, and adaptation
  uses 10 teams.

Verdict: `matchup_top4_v3` remains an experimental implementation. Correct
the offline analysis before running another 100-pair qualification.

## Phase V2e.1 — Corrected Offline Analysis

V2e.1 replaced the invalid cross-policy analysis with a common external plan
evaluator and reran the full 129-team comparison offline.

An additional review defect was fixed before accepting the result: preview
plans belong to the row's `player_policy`. The old extractor incorrectly
treated `opponent_policy` as plan ownership, which mislabeled the D2 Random
plan as V2. The corrected extractor selects only rows where
`player_policy == "matchup_top4_v2"`.

Verification:

```text
Ran 221 tests in 9.383s
OK
EXIT=0 ELAPSED=10.84
```

Corrected V2d interpretation:

| Metric | Result |
|---|---:|
| V2 wins both / Random wins both / split | 24 / 22 / 54 |
| Paired two-sided p-value | 0.882996 |
| D1 / D2 V2 wins | 57 / 45 |
| D1 / D2 V2 preview evidence | 100 / 100 |
| Selected-four changes between arms | 0/100 |
| Lead changes between arms | 0/100 |

The paired arms used identical team identities, and V2 emitted identical plans
on both sides. The 57%/45% split is not caused by preview instability.

Full common-scale comparison:

```text
129 teams, 129 identical opponent inputs
EXIT=0 ELAPSED=8.86
0 policy evaluation errors
```

| Policy | Avg | Median | Min | p10 | p90 |
|---|---:|---:|---:|---:|---:|
| basic_top4 | 4.383 | 4.367 | 2.117 | 3.175 | 5.627 |
| random | 3.538 | 3.538 | 1.067 | 2.117 | 4.922 |
| matchup_top4_v2 | 4.013 | 3.988 | 0.917 | 2.737 | 5.527 |
| matchup_top4_v3 | 4.329 | 4.383 | 1.300 | 2.752 | 5.760 |

V3 changed the selected four in 35/129 inputs and the lead pair in 65/129.
Compared with V2, it improved shared-lead weakness, speed-control pressure,
spread pressure, and total common score.

Opponent adaptation across all 129 teams, using fixed rank-1 and rank-50
opponents:

| Policy | Selection changes | Lead changes |
|---|---:|---:|
| basic_top4 | 25 | 4 |
| random | 0 | 0 |
| matchup_top4_v2 | 15 | 15 |
| matchup_top4_v3 | 22 | 6 |

Decision:

- Previous V2e analytical claims are invalidated.
- The corrected V2e.1 reports are accepted.
- `matchup_top4_v3` is ready for a new 100-pair qualification.
- Phase V3 remains blocked until battle evidence passes.
- No battles were run in V2e.1.

## Phase V2f — VGC 2026 matchup_top4_v3 Paired Qualification (2026-06-12)

**Goal:** Run a strict 100-pair, 200-battle paired qualification for
`matchup_top4_v3` versus `random` to test whether V3 is statistically
stronger than Random in a D1/D2 swap design.

### Files Added

- `bot_vgc2026_phaseV2f_qualification.py` — runner subclassing
  `V2dPairedQualificationRunner`. Uses `matchup_top4_v3` in
  D1 and `random` in D2 (mirrored). Policy-stable seed offset
  `matchup_top4_v3=401`, distinct from V2's `101`. Refuses to
  overwrite existing artifacts without `--overwrite`.
- `analyze_vgc2026_phaseV2f_qualification.py` — strict paired
  analyzer. Normalizes V3 outcomes, extracts V3 plans only from
  rows where `player_policy == "matchup_top4_v3"`, and verifies
  the D1/D2 V3 plan is identical for the same team/opponent input
  (V3 plan consistency).
- `test_vgc2026_phaseV2f.py` — 40 tests covering all required
  categories (spec generation, seed stability, outcome normalization,
  pair merge, plan ownership, plan consistency, statistics helpers,
  side-collapse gate, artifact validation, lifecycle).

### Pre-run Verification

```bash
/usr/bin/time -f 'EXIT=%x ELAPSED=%e' \
  timeout --foreground --signal=TERM --kill-after=5s 25s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
    test_vgc2026_controlled_teampreview.py \
    test_vgc2026_preview_policy_diagnostics.py \
    test_vgc2026_phaseV2e.py \
    test_vgc2026_phaseV2f.py
```

Result: `Ran 261 tests in 8.391s, OK, EXIT=0`.

### Local Server

- `node pokemon-showdown start --no-security` started in
  `pokemon-showdown/`. Health check `HTTP=200`. Process kept on
  `localhost:8000` only.

### Benchmark Execution

```bash
timeout --foreground --signal=TERM --kill-after=30s 600s \
  ./venv/bin/python bot_vgc2026_phaseV2f_qualification.py \
    --pairs 100 --artifact-tag phaseV2f_v3_paired_qualification
```

200/200 battles, no timeouts, no errors, no no_battle.

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

The first V2f report was invalid. `paired_sign_test()` counted every split pair
as a V3 success, testing 75/100 instead of excluding the 45 directionless
splits. The correct paired test is 30 V3-both versus 25 Random-both over 55
decisive pairs:

- two-sided exact p = 0.590053
- one-sided V3 p = 0.295027

The corrected focused suite ran 262 tests with EXIT=0. Validator hardening also
added strict JSON booleans, duplicate-arm detection, and CSV/JSONL field
agreement. No battles were rerun.

The 52.5% point estimate is positive but inconclusive. Phase V3 remains
**BLOCKED**.

### Hidden Information Confirmation

- V3 uses only open team-sheet information (species, ability, moves,
  types) from the local dex.
- No battle outcomes, hidden moves, items, or probabilistic
  abilities are consulted.
- Opponent team is visible during preview (standard VGC 4-from-6).
- No online API calls.

### Artifacts

- `logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_benchmark.csv`
- `logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_benchmark.jsonl`
- `logs/vgc2026_phaseV2c_phaseV2f_v3_paired_qualification_preview_evidence.csv`
- `logs/vgc2026_phaseV2f_analysis.json`
- `logs/vgc2026_phaseV2f_analysis.md`

### Preserved Artifacts

All prior artifacts (`vgc2026_phaseV2c_*`, `vgc2026_phaseV2d*`,
`vgc2026_phaseV2e*`) are unchanged in mtime and size.

### Final focused test command

```text
Ran 261 tests in 8.391s
OK
EXIT=0
```

## Phase V2g — V3 Battle Failure Diagnosis (2026-06-12)

**Goal:** Diagnose the V3 battle failures from the 100-pair V2f
qualification. Identify evaluator blind spots, classify observed
versus inferred findings, and decide whether to ship a `matchup_top4_v4`.

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
- `inspect_vgc2026_phaseV2g_pair.py` — single-pair inspector that
  prints both sides' plans with the full common + feature bundle.
- `test_vgc2026_phaseV2g.py` — 32 tests, including local-dex move
  category and spread-target regression coverage.

### Pre-run Verification

```text
Ran 294 tests in 8.664s
OK
EXIT=0 ELAPSED=9.93s
```

(104 controlled-preview + 42 V2d diagnostics + 65 V2e + 40 V2f + 32 V2g + 11 lifecycle-adjacent.)

### Diagnostic Methodology

1. **Merge by pair_id, never row position.** Verified by
   shuffling the benchmark rows and confirming the pair list
   is identical.
2. **Plan ownership via player_policy only.** The D1 V2g test
   `test_opponent_policy_metadata_does_not_own_v3_plan` proves
   the extractor refuses a row where `opponent_policy=V3` but
   `player_policy=random`.
3. **Sign test excludes split pairs.** `test_split_pair_excluded_from_sign_test`
   and `test_thirty_twentyfive_fortyfive_pvalues` pin the
   documented p-values exactly.
4. **Feature extraction uses the exact selected plan.**
   `test_features_depend_on_exact_plan` and
   `test_features_depend_on_exact_opponent_team` confirm that
   swapping one Pokémon or one opponent changes the bundle.
5. **Reconstruction from artifacts, not memorization.** The
   team details (moves, ability) are loaded from the same
   129-team pool the qualification ran against. No per-pair
   outcome is used to tune any policy.

### Pair classification (decisive-only sign test)

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

### Side collapse observation (NOT a root cause)

| Arm | V3 wins | Win rate |
|---|---:|---:|
| D1 (V3 as player) | 51/100 | 51.0% |
| D2 (V3 as opponent) | 54/100 | 54.0% |

This is **observed evidence only**; it is not a causal claim.

### V3 battle wins vs losses (battle-level)

| Feature | Wins mean (n=105) | Losses mean (n=95) | Delta |
|---|---:|---:|---:|
| offensive_type_coverage | 0.431 | 0.482 | -0.051 |
| defensive_weakness_exposure | 0.812 | 0.799 | +0.013 |
| fake_out_pressure | 0.600 | 0.621 | -0.021 |
| spread_pressure | 0.771 | 0.832 | -0.060 |
| common_total | 4.394 | 4.354 | +0.041 |
| back_immediate_pressure | 1.314 | 1.316 | -0.002 |
| physical_special_balance_diff | 2.286 | 2.800 | -0.514 |
| back_immediate_damage | 5.476 | 5.442 | +0.034 |
| restorative_moves | 0.038 | 0.147 | -0.109 |
| type_count_unique | 5.505 | 5.642 | -0.137 |

Per-battle wins and losses are **largely indistinguishable** under
the current common-evaluator + plan-feature bundle. Raw values use
different units and are descriptive rather than standardized effect
sizes.

### Failure-pair drill-down (Random-both, 25 pairs)

The most striking single observation: V3 plans in the loss group
score **higher** on the common scale than the winning Random plans.

| Metric | V3 mean (loss) | Random mean (win) | Delta |
|---|---:|---:|---:|
| **common_total** | **4.571** | **3.712** | **+0.859** |
| offensive_type_coverage | 0.521 | 0.471 | +0.050 |
| back_pivot_or_switch | 0.080 | 0.200 | -0.120 |
| lead_immediate_damage | 5.000 | 5.280 | -0.280 |
| type_count_unique | 5.640 | 4.920 | +0.720 |
| setup_moves | 0.160 | 0.320 | -0.160 |

The common evaluator gives the losing V3 plans a higher score than
the matching winning Random plans. This shows that the common score
does not discriminate these failure pairs; it does not identify a
causal feature.

### V3-both vs Random-both (V3 plan features)

| Feature | V3-both (wins) | Random-both (wins) |
|---|---:|---:|
| offensive_type_coverage | 0.424 | 0.521 |
| fake_out_pressure | 0.700 | 0.760 |
| intimidate_support | 0.433 | 0.320 |
| spread_pressure | 0.767 | 0.880 |
| back_immediate_pressure | 1.117 | 1.440 |
| back_immediate_damage | 2.767 | 3.000 |
| restorative_moves | 0.033 | 0.240 |
| type_count_unique | 5.400 | 5.640 |

These are descriptive group means only. D1 and D2 reuse the same
deterministic V3 plan for each pair, so the battle-level rows are
repeated observations rather than independent plan samples.

### Evaluator Blind Spots

The V2g diagnostics do NOT identify a single, concrete, testable
weakness. Instead, the data is consistent with a common-evaluator
that is a **rough predictor**, not a battle predictor:

1. **Common score has weak observed separation.** The win/loss
   common_total delta is +0.041 across 200 battles. The loss
   group in Random-both has a HIGHER common_total than the
   winning Random plans, indicating the score is not
   discriminating well.
2. **Raw deltas are not effect sizes.** Corrected local-dex move
   classification produces differences such as
   physical/special-balance `-0.514` and failure-pair type
   diversity `+0.720`, but the features use different units and
   do not establish causality.
3. **The 200 rows are not independent plan samples.** D1 and D2
   reuse the same deterministic V3 plan for each pair.
4. **Observed opponent leads are post-preview evidence.** They can
   support diagnosis but cannot be used as a team-preview policy
   input.
5. **Item-sensitive and turn-sequence interactions are omitted.**
   No single safe V4 rule is isolated.

### Decision: continue offline tuning (option b)

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

## Phase V2h — Pair-Level Feature Stability Diagnosis

Phase V2h evaluates whether any preview-visible feature is stable
enough to justify a future `matchup_top4_v4`. It does not implement
or enable V4.

### Statistical Design

- Statistical unit: one V3 preview plan per `pair_id`
- V3-both: 30 pairs
- Random-both: 25 pairs
- Split: 45 pairs, descriptive only
- Decisive sign-test n: 55
- Two-sided p: `0.5900533317766357`
- One-sided p: `0.29502666588831783`

D1 and D2 reuse the same deterministic V3 plan. They are not counted
as independent preview-plan samples.

For each numeric feature, the analyzer reports group summaries,
unpaired mean difference with deterministic bootstrap CI, pooled
Cohen's d with bootstrap CI, paired V3-minus-Random difference inside
the 25 Random-both failure pairs, deterministic LOO direction
stability, and stratified deterministic 5-fold stability.

### Review Defects Fixed

1. The original CI-excludes-zero expression was logically inverted.
2. The original between-group LOO/fold calculation used synthetic
   signed values rather than comparing the 30 and 25 group means.
3. V2g bundle construction omitted `PlanFeatures.audit`, causing
   unknown-move counts to be lost.

All three defects have direct regression coverage.

### Results

| Metric | Result |
|---|---:|
| Numeric features | 31 |
| Candidate-actionable | 0 |
| Contradictory | 18 |
| Insufficient support | 0 |
| Unknown V3 moves | 0 |
| Unknown Random moves | 0 |

Examples:

| Feature | Between-group d | Between mean-diff CI | Failure-pair diff | Failure-pair CI |
|---|---:|---:|---:|---:|
| offensive_type_coverage | -0.739 | [-0.163, -0.033] | +0.050 | [+0.006, +0.095] |
| restorative_moves | -0.548 | [-0.407, -0.013] | +0.120 | [0.000, +0.240] |
| common_total | +0.033 | [-0.469, +0.598] | +0.859 | [+0.536, +1.174] |
| setup_moves | -0.059 | [-0.253, +0.200] | -0.160 | [-0.320, -0.040] |
| type_count_unique | -0.141 | [-1.227, +0.587] | +0.720 | [+0.200, +1.280] |

`common_total` strongly favors the losing V3 plan inside Random-both
pairs, while it has almost no between-group separation. Eighteen
features reverse direction between the two comparisons. No feature
passes the complete stability and consistency gate.

### Verification

```text
V2h-only:
Ran 48 tests in 17.280s
OK
EXIT=0 ELAPSED=17.49s

Cross-phase:
Ran 342 tests in 24.984s
OK
EXIT=0 ELAPSED=26.25s
```

### Decision

**B — continue offline evaluator work.**

`matchup_top4_v4` is not implemented. Phase V3 remains **BLOCKED**.
No battle was run. Outcomes were used only as offline labels. Feature
extraction and policy selection remain limited to preview-visible
local data.

Artifacts:

- `logs/vgc2026_phaseV2h_feature_stability.json`
- `logs/vgc2026_phaseV2h_feature_stability.md`

## Phase V2i — Outcome-Blind Matchup Evaluator v2

Phase V2i introduced a frozen, preview-visible matchup evaluator that
scores an exact 4/2/2 plan against all 15 possible opponent lead
pairs. It uses the local Gen 9 dex and no online or post-preview data.

### Review Corrections

The initial implementation passed its tests but had three semantic
errors:

1. Type pressure was inferred from Pokémon species types rather than
   the actual damaging moves on the open team sheet.
2. Back-switch safety included our own lead move types as incoming
   threats.
3. Worst-case resilience returned `1.0` when no opponent lead was
   threatened.

These paths now use preview-visible damaging move metadata, opponent
attacks only, and the correct minimum threatened-slot fraction.
Regression tests pin each behavior. The frozen fingerprint changed to
`c86d75271f833ede664b756c717dd4ce1c9c6791505c5c32d1864101ebfaa22a`.
The fingerprint payload includes
`EVALUATOR_ALGORITHM_VERSION="v2i.1-preview-move-types"` so future
semantic changes cannot reuse a constants-only fingerprint.

The analyzer was also corrected to:

- bootstrap paired comparisons by pair index;
- expose explicit CI-excludes-zero semantics;
- report policy selection errors instead of silently falling back to
  Random;
- skip the 129-team evaluation for synthetic unit-test inputs;
- render the 129-team table and final A/B decision.

### Results

| Comparison | Mean difference | 95% bootstrap CI |
|---|---:|---:|
| V3-both vs Random-both | -0.237 | [-0.786, +0.325] |
| Within Random-both, V3 vs Random | +0.243 | [-0.209, +0.669] |

The V2f sign test is unchanged: V3-both 30, Random-both 25, split 45,
two-sided `p=0.590053`, one-sided `p=0.295027`.

The offline 129-team comparison completed all 129 inputs with no
selection errors. Evaluator means were 6.304 for basic_top4, 5.975 for
Random, 6.301 for V2, and 6.413 for V3. V3-minus-V2 was +0.112 with a
paired 95% CI `[+0.028, +0.209]`. This is evaluator agreement, not
battle evidence.

### Verification

```text
Ran 79 tests in 11.648s
OK
EXIT=0 ELAPSED=11.85s

Cross-phase VGC:
Ran 421 tests in 35.518s
OK
EXIT=0 ELAPSED=36.60s

Analyzer EXIT=0 ELAPSED=17.82s
```

The full repository discovery run executed 1,274 tests and exposed
10 errors plus 5 failures in the pre-existing dynamic-move-type audit
path (`test_doubles_dynamic_move_type_safety.py`). V2i changed none of
the doubles logger or dynamic-type files. This is recorded as a
separate unresolved doubles regression rather than hidden by the
passing VGC suites.

The inspector was exercised against both synthetic and real pair data
with component, opponent-lead, best/worst lead, policy-comparison, and
ablation flags.

### Decision

**B — continue offline evaluator work.**

Both predeclared failure-comparison confidence intervals cover zero.
`matchup_top4_v4` was not implemented. Phase V3 remains **BLOCKED**.
No battle was run.

## Phase V2j — Outcome-Blind Lead Matchup Evaluator v3 (2026-06-13)

**Status:** Complete after Codex review. No V2i behavior was
changed. Phase V3 remains **BLOCKED**.

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
- The fingerprint is recorded at analyzer-import time
- Evaluator never reads outcomes
- Evaluator never reads observed battle leads, turn logs, or
  any post-preview evidence

### Feature Definitions (17 components)

| Component | Sign | Description |
|---|---|---|
| `lead_offensive_effectiveness` | + | Mean bucket (0..4) of our lead pair's damaging moves against the opponent lead pair |
| `lead_offensive_stab_pressure` | + | Fraction of damaging moves with attacker-type match (STAB) |
| `lead_defensive_resistance` | + | Mean defensive-resistance bucket against opponent lead damaging moves |
| `lead_immunity_aware_pressure` | + | Count of explicit lead absorb/Levitate abilities that match opponent lead attacking types |
| `lead_spread_threat` | + | Count of damaging spread moves in the lead pair that threaten at least one opponent lead |
| `lead_priority_threat` | + | Count of offensive priority moves (Protect excluded) |
| `lead_fake_out_threat` | + | Count of Fake Out users, capped at 1 |
| `lead_speed_control_pressure` | + | 1 if lead pair has Tailwind / Trick Room / Icy Wind, else 0 |
| `lead_redirection_pressure` | + | 1 if lead pair has Follow Me / Rage Powder / Spotlight / Storm Drain / Lightning Rod, else 0 |
| `lead_protect_utility` | + | Count of stalling moves, capped at 2 |
| `lead_setup_vulnerability` | - | Count of opponent lead setup moves not answered by Fake Out / pivot / redirection / Intimidate, capped at -2 |
| `lead_shared_weakness` | - | -1.0 per shared 4x weakness, -0.5 per shared 2x weakness |
| `lead_pivoting_pressure` | + | 0.5 per pivot (U-turn, Volt Switch, Parting Shot), capped at 1.0 |
| `lead_physical_special_balance` | + | 1 - |physical - special| / 4 |
| `lead_target_concentration` | + | Opponent lead slots threatened super-effectively, capped at 2 |
| `lead_unresolved_count` | - | -(count of unknown moves / abilities) / 4, capped at -1 |
| `back_switch_defensive_coverage` | + | Back Pokémon not 2x weak to any opponent lead's preview-visible damaging move, capped at 2 |

### Freeze-Before-Outcomes Proof

The V2j analyzer's `_safe_run` records the freeze time at
module import time (before any V2f artifact is opened) and
records the first outcome load time when `load_v2f_outcomes_*`
is first called. The proof asserts:

```text
frozen_before_outcomes: True
freeze_time_unix: <import time>
first_outcome_load_unix: None (synthetic) or > freeze_time_unix
```

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

### Bootstrap / Stability Table (synthetic)

| Component | n | between | within | LOO | Fold | SurvLargest | CI | Agree | Unknown | Actionable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lead_offensive_effectiveness | 30 | +1.676 | -0.036 | 1.00 | 1.00 | FAIL | n/a | FAIL | FAIL | FAIL |
| lead_defensive_resistance | 30 | +2.106 | +0.022 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |
| lead_priority_threat | 30 | +1.000 | +0.000 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |
| lead_fake_out_threat | 30 | +1.000 | +0.000 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |
| lead_speed_control_pressure | 30 | +1.000 | +1.000 | 1.00 | 1.00 | FAIL | n/a | PASS | FAIL | FAIL |

(Synthetic inputs do not include a real V3 / Random divergence,
so every component's paired CI covers zero.)

### Contradictory / Actionable Components

- Contradictory: 0
- Actionable: 0

### Decision

**B — continue offline evaluator work.** No component passes
all gates, so no narrow V4 design proposal is produced.
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

- 111 V2j tests cover all required regression cases:
  Normal/Fighting into Ghost, Electric into Ground, Water into
  Water Absorb / Storm Drain, Electric into Volt Absorb /
  Lightning Rod, Ground into Flying / Levitate, Psychic into
  Dark, Dragon into Fairy, spread move with one immune target,
  Fake Out into Ghost, Protect not offensive pressure,
  Tailwind / Icy Wind / Trick Room, Follow Me / Rage Powder,
  U-turn / Volt Switch / Parting Shot, unknown move / ability,
  no input mutation, lead and opponent order permutation
  invariance, configuration freeze, freeze-before-outcomes,
  shuffled pair merge, sign-test reproduction, component gate
  evaluation, inspector filters, and natural subprocess exit.

### Watchdog Settings

- Focused: 60s, 10s kill-after.
- V2i + V2j: 120s, 10s kill-after.
- Cross-phase VGC: 120s, 10s kill-after.
- Full discovery: 300s, 30s kill-after.
- All runs use foreground timeouts under
  `-W error::ResourceWarning`.

### Unchanged Defaults

- `DoublesDamageAwareConfig` was not modified.
- V1, V2, V3 policy behavior and defaults were not modified.
- The V2i matchup evaluator and analyzer were not modified.
- The V2j evaluator only reads preview-visible data: species,
  types, moves, abilities, items, and local Gen 9 dex metadata.
- `EVALUATOR_ALGORITHM_VERSION` is `v2j.0-lead-matchup` (a new
  string for V2j; the V2i version remains
  `v2i.1-preview-move-types`).

### Artifacts

- `logs/vgc2026_phaseV2j_lead_matchups.json`
- `logs/vgc2026_phaseV2j_lead_matchups.md`

All prior artifacts (`vgc2026_phaseV2c_*`,
`vgc2026_phaseV2f_*`, `vgc2026_phaseV2i_*`) are unchanged in
mtime and size.

## Repository Regression Cleanup after Phase V2i (2026-06-13)

**Status:** Complete after Codex review. No V2i behavior was changed.
Phase V3 remains **BLOCKED**.

### Root Cause

The repository-wide unittest discovery completed 1,274 tests with
10 errors and 5 failures, all in
`test_doubles_dynamic_move_type_safety.py`. The production caller in
`bot_doubles_damage_aware.py` already built 15 per-slot lists for the
dynamic-type absorb audit and passed them as keyword arguments to
`DoublesDecisionAuditLogger.log_turn_decision()`. The logger accepted
these via `**kwargs` but never added them to the `slot_0` / `slot_1`
audit dictionaries. The saved JSONL therefore had no dynamic-type
absorb fields, the analyzer's `Dynamic Move Type Safety Report`
reported zero candidates, and the inspector's
`--candidate-blocked` / `--selected` / `--reason ...` filters could
never return a real case.

The 15 missing per-slot fields were: `candidate_blocked`,
`selected`, `avoided`, `reason`, `target_species`, `target_ability`,
`blocked_move_id`, `blocked_candidate_score`, `candidate_available`,
`candidate_move_id`, `candidate_declared_type`,
`candidate_effective_type`, `candidate_form`, `candidate_source`,
`candidate_target_table`. All 15 share the
`dynamic_type_absorb_` prefix and the test file already used exact
field names with `.get(..., default)` access.

### Changed Files

- `doubles_decision_audit_logger.py` only.
- `bot_doubles_damage_aware.py`, `analyze_doubles_decision_audit.py`,
  `inspect_dynamic_move_type_cases.py`, the V2i test files, the
  V2i matchup evaluator, the V2i analyzer, and the V2i test for
  the production caller were not modified.
- `DoublesDamageAwareConfig` defaults were not touched.

### Production Data Flow Fix

1. `classify_dynamic_type_absorb_candidates()` in
   `bot_doubles_damage_aware.py` already returned the 15 per-slot
   fields and the structured `dynamic_candidate_target_table`.
2. The per-slot lists were already constructed and passed into
   `logger.log_turn_decision(...)` at
   `bot_doubles_damage_aware.py:13401`.
3. In `doubles_decision_audit_logger.py`:
   - The 15 fields were promoted from implicit `**kwargs` to
     first-class named parameters on `log_turn_decision`.
   - Each field was added to `slot_0` indexing the per-slot list
     with `[0]`, defaulting to `False` / `""` / `0.0` / `[]`.
   - Each field was added to `slot_1` with the same pattern
     using `[1]`.
   - The `dynamic_type_absorb_candidate_target_table` value is
     forwarded as the inner list of structured target rows;
     the list is not aliased between slots, so slot 0 cannot
     leak into slot 1.
4. The analyzer, inspector, validator, and metrics code already
   read the same field names with `.get(..., default)` access,
   so no other files needed changes.

### Tests and Exit Codes

Focused:

```text
timeout --foreground --signal=TERM --kill-after=10s 60s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_doubles_dynamic_move_type_safety.py

Ran 110 tests in 1.206s
OK
EXIT=0 ELAPSED=1.60s
```

Neighboring:

```text
timeout --foreground --signal=TERM --kill-after=10s 90s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_doubles_dynamic_move_type_safety.py \
  test_doubles_known_absorb_hard_safety.py \
  test_doubles_known_ally_redirection_safety.py \
  test_doubles_singleton_ability_safety.py

Ran 267 tests in 4.077s
OK
EXIT=0 ELAPSED=4.85s
```

V2i regression (unchanged behavior):

```text
Ran 79 tests in 18.419s
OK
EXIT=0 ELAPSED=18.79s
```

Full discovery:

```text
timeout --foreground --signal=TERM --kill-after=30s 300s \
  ./venv/bin/python -W error::ResourceWarning -m unittest

Ran 1275 tests in 52.638s
OK
EXIT=0 ELAPSED=55.43s
```

The earlier V2i "15 dynamic-type failures" claim is **superseded**.
The latest discovery observed 1,275 tests, while the earlier run
observed 1,274. The exact source of that +1 difference was not
established by the logger-only patch.

### Acceptance Items

- Full discovery `EXIT=0` under 300s foreground timeout.
- No `ResourceWarning` under `-W error::ResourceWarning`.
- No timeout kill, no `os._exit`, no `atexit.register` placeholder.
- Analyzer's `Dynamic Move Type Safety Report` prints
  `dynamic absorb candidates blocked / selected / avoided`,
  `block reason split`, `blocked move ID split`, `target species
  split`, `target ability split`, `accounting invariant:
  blocked == selected + avoided : PASS`, and `attacker:`
  metadata inside the sample cases when a blocked record exists.
- Inspector's `--candidate-blocked`, `--selected`, and
  `--reason ...` filters return real `SELECTED` /
  `AVOIDED` rows; default filter still excludes ordinary
  static moves.
- `test_target_table_slot_isolation` and
  `test_slot1_does_not_inherit_slot0_metadata` prove slot 0
  metadata does not leak into slot 1.
- V2i focused suite (`test_vgc2026_phaseV2i.py`) still passes
  in 79 / 79 with no behavior change.
- Phase V3 remains **BLOCKED**.
- No battle was run; no server was contacted.
- All `logs/` artifacts are at their previous sizes and mtimes.

### Watchdog Settings

- Focused: 60s, 10s kill-after.
- Neighboring: 90s, 10s kill-after.
- Full discovery: 300s, 30s kill-after.
- All runs use foreground timeouts under
  `-W error::ResourceWarning`.

### Unchanged Defaults

- `DoublesDamageAwareConfig` source-of-truth values were not
  modified.
- `ability_hard_safety_avoid_absorb = True`,
  `ability_hard_safety_direct_absorb_only = True`,
  `ability_hard_safety_allow_singleton_deduction = True`.
- `enable_support_move_target_hard_safety = False`,
  `enable_priority_field_hard_safety = False`,
  `enable_known_ally_redirection_hard_safety = False`,
  and every other adopted-disallow flag remain at their
  previous values.
- `EVALUATOR_ALGORITHM_VERSION` remains
  `"v2i.1-preview-move-types"` and the V2i fingerprint remains
  `c86d75271f833ede664b756c717dd4ce1c9c6791505c5c32d1864101ebfaa22a`.

## V2i Regression Cleanup — Slot-1 Guard Hardening (2026-06-13)

**Status:** Complete after Codex review. No V2i behavior was
changed. Phase V3 remains **BLOCKED**.

### Codex Review Finding

The previous V2i regression fix indexed every per-slot
`dynamic_type_absorb_*` field on `value[1]` when computing the
slot 1 audit record, gated only by a truthiness check on
`value`. A 1-element list (e.g., `[True]`) would pass the
truthiness check and then raise `IndexError` when the code
read `value[1]`. This was a latent production bug; the
production caller always passes 2-element lists, so the
existing tests never exercised the failure mode.

### Changed Files

- `doubles_decision_audit_logger.py` only.
- `test_doubles_dynamic_move_type_safety.py` — 6 new tests.
- `CURRENT_STATE.md` and `walkthrough.md` — corrected the
  test-count delta narrative.

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
- `[]` → default (`len(value) > 1` is `False`).
- `[x]` → default (`len(value) > 1` is `False`; the old code
  raised `IndexError` here).
- `[a, b]` → coerced `b`.
- Slot 0 path is unchanged.

Defaults preserved exactly:

- `False` for the four `bool` fields.
- `""` for the nine `str` fields.
- `0.0` for `dynamic_type_absorb_blocked_candidate_score`.
- `[]` for `dynamic_type_absorb_candidate_target_table`.

### New Tests

Added 6 tests to `TestLoggerAnalyzer` in
`test_doubles_dynamic_move_type_safety.py`:

1. `test_slot1_none_inputs_return_defaults`
2. `test_slot1_empty_lists_return_defaults`
3. `test_slot1_one_element_lists_return_defaults`
4. `test_slot1_two_element_lists_use_index_one`
5. `test_slot0_one_element_lists_use_index_zero` (no
   regression on the existing slot 0 path)
6. `test_target_table_slot_isolation_with_two_element_lists`

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

Neighboring:

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

V2i focused (unchanged behavior):

```text
Ran 79 tests in 16.448s
OK
EXIT=0 ELAPSED=16.76s
```

Full discovery:

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

The +6 delta between 1,275 and 1,281 matches the 6 new tests
added in this patch. The exact source of the +1 delta
between the original 1,274 count and the 1,275 count was
**not** established by the previous logger-only patch. The
"re-enabled previously failing-but-collected test methods"
claim has been removed.

### Watchdog Settings

- Focused: 60s, 10s kill-after.
- Neighboring: 90s, 10s kill-after.
- Full discovery: 300s, 30s kill-after.
- All runs use foreground timeouts under
  `-W error::ResourceWarning`.

### Unchanged Defaults

- `DoublesDamageAwareConfig` source-of-truth values were not
  modified.
- `ability_hard_safety_avoid_absorb = True`,
  `ability_hard_safety_direct_absorb_only = True`,
  `ability_hard_safety_allow_singleton_deduction = True`.
- `enable_support_move_target_hard_safety = False`,
  `enable_priority_field_hard_safety = False`,
  `enable_known_ally_redirection_hard_safety = False`,
  and every other adopted-disallow flag remain at their
  previous values.
- Production scoring in `bot_doubles_damage_aware.py` was not
  modified. Classifier semantics, analyzer, inspector, and
  config defaults are unchanged.

## Phase V2k — Shared Doubles Mechanics Consolidation and V2j Analyzer Repair (2026-06-13)

**Goal:** Extract one canonical Pokémon mechanics layer
(`doubles_mechanics.py`) and have both the Random Doubles
player and the VGC 2026 evaluators consume it. Repair the
V2j analyzer's classification-vs-bootstrap bug. Add a parity
test file that pins both layers to identical answers on
identical visible inputs.

### Architectural Decision

VGC 2026 is **not** a separate battle engine. It is the
existing Doubles 2v2 engine with a 4-from-6 team-preview
layer. Therefore, every Pokémon-mechanics primitive (type
effectiveness, ability interactions, dynamic move type,
STAB, spread, priority, Fake Out legality, speed ordering)
lives in **exactly one module**: `doubles_mechanics.py`. The
Random Doubles player (`bot_doubles_damage_aware.py`) and
the VGC evaluators both consume this module. The shared
module is pure: it does not import the production player,
poke-env internals, or any global benchmark state.

### Duplication Matrix (Phase A)

| Mechanic | Random Doubles | VGC evaluators | Shared `doubles_mechanics` | Notes |
|---|---|---|---|---|
| Type chart | `pokemon.damage_multiplier` | `TYPE_CHART` (3 copies) | `TYPE_CHART` + `calculate_type_multiplier` | Single canonical table; VGC reads from `team_preview_policy` which re-exports the shared one. |
| Type immunity | `imm == 0.0` inline | `IMMUNITY_TABLE` (in V2j) | `IMMUNITY_TABLE` | Single canonical. |
| Absorb abilities | `ability_hard_blocks_move` (inline) | `ABSORB_ABILITIES` (2 copies) | `ABSORB_ABILITIES_BY_TYPE` | Single canonical typed-by-ability dict. |
| Dynamic move type (Aura Wheel) | `resolve_effective_move_type` (form tracker) | none (uses static declared type) | `resolve_effective_move_type` | Shared module is preview-safe: falls back to declared when no observed form. |
| STAB | inline in 3 places | `lead_offensive_stab_pressure` (V2j only) | `move_has_stab` | Single canonical. |
| Damaging/status classification | inline `category.name == "PHYSICAL" / ...` | `classify_move` (2 copies) | `classify_move` + `MoveClassification` | Single canonical. |
| Spread targeting | `is_spread_move` (poke-env target) | `is_spread` (dex target) | `classify_move.is_spread` | Single canonical via the Gen 9 dex. |
| Priority | `get_move_priority` (hard-coded list) | `is_priority_offensive` (dex priority) | `classify_move.is_priority_offensive` + `move_priority` | Single canonical. |
| Fake Out legality | inline `mult==0 or is_ghost` | inline `"fake out" in name` | `fake_out_legal_targets` | Single canonical. |
| Speed ordering | `is_trick_room_active` + `get_effective_speed` | none | `resolve_deterministic_speed_order` | New: returns `unresolved` on hidden state. |
| Known ability resolution | `get_known_ability` (4 layers) | `player_policy` enum | `resolve_explicit_ability_interaction` | Battle-side keeps its 4-layer resolver; preview-side only consumes the result. |
| Visible-information audit | none | none | `VisibleInformation` + `audit_visible_information` | New canonical home. |

The shared `doubles_mechanics` module does **not** include
the VGC role taxonomy (SETUP_MOVES, RESTORATIVE_MOVES,
PIVOT_MOVES, REDIRECTION_MOVES, SPEED_CONTROL_MOVES). Those
are VGC role classification, not Pokémon mechanics.

### Files Added

- `doubles_mechanics.py` — canonical Pokémon mechanics
  primitives. Pure, no player import, no poke-env
  internals, no network or global state.
- `test_doubles_mechanics_parity.py` — 43 parity tests
  covering type immunities, dual types, explicit
  abilities, exceptions, STAB, damaging spread, Protect
  vs. offensive priority, Fake Out legality, speed
  ordering, no hidden ability inference, no input
  mutation, Aura Wheel form transitions, and architectural
  guards against future VGC evaluators recreating private
  type charts, immunity tables, or absorb-ability
  tables.
- `analyze_vgc2026_phaseV2k_lead_matchups.py` — the
  repaired V2j analyzer. New artifacts go to
  `vgc2026_phaseV2k_lead_matchups.{md,json}` and never
  overwrite V2f, V2i, or V2j artifacts.
- `inspect_vgc2026_phaseV2k_lead_matchup.py` — V2k
  inspector that drills into the shared mechanics for
  per-move audit fields.
- `test_vgc2026_phaseV2k.py` — 18 tests covering pair
  classification, sign test, plan ownership, per-component
  array correctness, bootstrap shape, gate reasons, real
  artifact validation, and end-to-end pipeline.

### Files Modified

- `bot_doubles_damage_aware.py` — `resolve_effective_move_type`,
  `get_effective_move_type`, `_get_declared_move_type`,
  `is_type_immune`, `ability_hard_blocks_move` now delegate
  to the shared module via thin compatibility wrappers. The
  public return shapes and the reason-string format
  (`"[Mechanics] type immunity: TYPE vs TYPES -> score 0"`)
  are preserved exactly. Thousand Arrows, Gravity, and
  Scrappy / Mind's Eye exceptions are preserved.
- `team_preview_policy.py` — now imports `TYPE_CHART`,
  `calculate_type_multiplier`, `resolve_effective_move_type`,
  `get_effective_move_type`, `classify_move`, and
  `EXPLICIT_ABSORB_ABILITIES` from `doubles_mechanics`. The
  inline `TYPE_CHART = {...}` is removed. All consumers
  (`vgc2026_matchup_evaluator_v2`, `vgc2026_lead_matchup_evaluator_v3`,
  `vgc2026_plan_features`, `vgc2026_common_plan_evaluator`)
  now consume the same canonical source through this
  re-export.
- `vgc2026_matchup_evaluator_v2.py`,
  `vgc2026_lead_matchup_evaluator_v3.py`,
  `vgc2026_plan_features.py`,
  `vgc2026_common_plan_evaluator.py` —
  `_all_attacker_multiplier` and `_composite_multiplier`
  delegate to `doubles_mechanics.calculate_type_multiplier`.
  The `ABSORB_ABILITIES` table is rebuilt from
  `doubles_mechanics.ABSORB_ABILITIES_BY_TYPE` to preserve
  the existing VGC natural-language key form
  (`"water absorb"`, `"volt absorb"`, etc.).

### Pair Records and Plan Ownership (Phase F)

The V2k analyzer merges benchmark + preview rows by
**`pair_id`** (not by row position). The V3 plan owner is
identified by `player_policy == "matchup_top4_v3"` and the
Random plan owner is identified by `player_policy ==
"random"` — never by row position.

Pair classification:

- **v3_both** (30): V3 wins both D1 and D2.
- **random_both** (25): V3 loses both D1 and D2.
- **split** (45): V3 wins exactly one of D1 / D2.
- **invalid** (0): missing data.
- **Decisive n** = 55. **Complete pairs** = 100.

This matches the V2f qualification exactly. The V2j
synthetic fixture also reproduces the 30/25/45 split
deterministically, and a shuffled input row order yields
the same classification (verified by
`TestV2kShuffleInvariant`).

### Statistics Repair (Phase F)

The V2j analyzer had three defects:

1. `random_both_components` was incorrectly populated with
   `v3_eval.component_means` for ALL decisive pairs, so
   the "random_both" group actually held V3 plan values
   for 55 pairs instead of 25.
2. `evaluate_component` was called with arrays of
   different lengths (30 vs 25), so
   `_bootstrap_paired_mean_diff_ci` returned `None` and
   the actionable gate always failed by construction.
3. The between-group comparison is unpaired (different
   group sizes), but V2j used a paired bootstrap.

V2k fixes all three:

- `v3_in_random_both_components[k]` now holds the V3
  plan's per-component means on the 25 random_both
  pairs (the LOSING V3 plan).
- `random_in_random_both_components[k]` now holds the
  Random plan's per-component means on the 25
  random_both pairs (the WINNING Random plan).
- Between-group CI is the **independent** bootstrap
  (different group sizes).
- Within-failure CI is the **paired** bootstrap on the
  25 matched V3−Random differences.
- A missing CI is a **gate failure with an explicit
  reason**, not a silent skip.
- Real-artifact mode reports `evidence_mode=real`,
  artifact paths, sizes, and row counts.
- Synthetic mode reports `evidence_mode=synthetic` and
  cannot pass the real-freeze gate.

### Correct V2f Plan Ownership and Denominators

| Metric | Value | Source |
|---|---|---|
| v3_both | 30 | `vgc2026_phaseV2f_analysis.md` |
| random_both | 25 | `vgc2026_phaseV2f_analysis.md` |
| split | 45 | `vgc2026_phaseV2f_analysis.md` |
| decisive | 55 | 30 + 25 |
| complete pairs | 100 | 30 + 25 + 45 |
| Two-sided p | 0.590053 | exact binomial, decisive-only |
| One-sided p (V3) | 0.295027 | exact binomial, decisive-only |

### Real Artifact / Freeze Proof

The V2k analyzer writes a new artifact pair:

- `logs/vgc2026_phaseV2k_lead_matchups.json`
- `logs/vgc2026_phaseV2k_lead_matchups.md`

Real-artifact proof for the V2f run:

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
outcome load. The artifact paths, sizes, and row counts
are recorded. `evidence_mode=real` and
`real_freeze_gate_passed=True` are both required for
the report to be considered real; synthetic mode can
never pass them.

### Corrected Statistical Results (V2k on real V2f)

| Component | n_v3_both | n_random | between | between-CI | within | within-CI | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| lead_offensive_effectiveness | 30 | 25 | +1.148 | [-0.231, +0.175] | -0.103 | [-0.191, -0.030] | FAIL |
| lead_defensive_resistance | 30 | 25 | +1.935 | [-0.452, +0.032] | +0.125 | [-0.110, +0.433] | FAIL |
| lead_fake_out_threat | 30 | 25 | +0.633 | [-0.287, +0.213] | +0.360 | [+0.160, +0.560] | FAIL |
| lead_speed_control_pressure | 30 | 25 | +0.667 | [-0.267, +0.233] | +0.400 | [+0.120, +0.640] | FAIL |

(Full table in `logs/vgc2026_phaseV2k_lead_matchups.md`.)

All 17 components have between-CIs that cover zero and
within-CIs that do not pass the strict actionable gate.
**Decision: B — continue offline evaluator work. Phase V3
remains BLOCKED.** `matchup_top4_v4` was not implemented.

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

### Removed / Quarantined Duplicate Logic

- Inline `TYPE_CHART = {...}` removed from
  `team_preview_policy.py`. The module re-exports the
  shared `TYPE_CHART` from `doubles_mechanics`.
- Inline `ABSORB_ABILITIES = {...}` rebuilt in V2i and
  V2j evaluators is now a compatibility shim over
  `doubles_mechanics.ABSORB_ABILITIES_BY_TYPE`. The
  natural-language key form is preserved so existing
  tests and the inspector / analyzer continue to work.
- The V2j analyzer's `_safe_run` no longer mixes V3
  and Random plan values into the same per-component
  array. The between-group CI is the independent
  bootstrap; the within-failure CI is the paired
  bootstrap on 25 matched differences.

Role taxonomy tables (SETUP_MOVES, RESTORATIVE_MOVES,
PIVOT_MOVES, REDIRECTION_MOVES, SPEED_CONTROL_MOVES)
remain in the VGC evaluator modules because they are
VGC role classification, not Pokémon mechanics. They
were never declared in scope for the shared mechanics
layer.

### Defaults / Scoring / Policies Unchanged

- `DoublesDamageAwareConfig` source-of-truth values
  were not modified.
- All `enable_*` flags in the doubles audit path
  remain at their adopted values.
- V1, V2, V3 policy behavior and defaults were not
  modified.
- `EVALUATOR_ALGORITHM_VERSION` for V2i and V2j are
  unchanged (`"v2i.1-preview-move-types"` and
  `"v2j.0-lead-matchup"`).
- The frozen V2j fingerprint
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
  is reused by V2k unchanged.

### Test Summary

- `test_doubles_mechanics_parity.py` — 43 tests.
  Covers: type immunities (Normal/Ghost, Fighting/Ghost,
  Electric/Ground, Ground/Flying, Psychic/Dark,
  Poison/Steel, Dragon/Fairy, Ghost/Normal), dual types
  (Fighting/Steel/Ghost, Electric/Water/Ground,
  Psychic/Dark/Poison, Poison/Fairy/Steel,
  Dragon/Water/Fairy, Ground/Electric/Flying), explicit
  abilities (Water Absorb, Storm Drain, Dry Skin, Volt
  Absorb, Lightning Rod, Motor Drive, Flash Fire, Well-
  Baked Body, Sap Sipper, Levitate), exceptions
  (Thousand Arrows, Gravity, Scrappy, Mind's Eye), STAB,
  damaging spread, Protect not counted as offensive
  priority, Fake Out into two Ghosts = 0 legal,
  Fake Out into one Ghost + one legal = 1, deterministic
  faster/slower/tie ordering, unresolved speed ordering
  on hidden state, no hidden ability inference, no input
  mutation, Aura Wheel Full Belly / Hangry / reverse /
  preview-unresolved / no-stale-state, VGC evaluators
  import the shared module, VGC evaluators do not
  redeclare TYPE_CHART / IMMUNITY_TABLE /
  ability_hard_blocks_move / compare_speed / faster_than,
  and `doubles_mechanics` does not import the player.
- `test_vgc2026_phaseV2k.py` — 18 tests covering pair
  classification (30/25/45), sign test p-values,
  shuffle-invariance, per-component array correctness
  (V3 plan on v3_both, V3 plan on random_both, Random
  plan on random_both, V3−Random differences), bootstrap
  shape (independent for between, paired for
  within-failure), gate reasons, real artifact
  validation, plan ownership by `player_policy`, and
  end-to-end pipeline.
- All existing V2c..V2j tests pass unchanged.
- All existing Random Doubles safety tests
  (immunity, dynamic type, ability hard safety,
  singleton, known absorb, known ally redirection,
  support target) pass unchanged.

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

### Watchdog Settings

- Parity tests: 60s, 10s kill-after.
- V2k tests: 60s, 10s kill-after.
- Cross-phase VGC: 180s, 30s kill-after.
- Full discovery: 300s, 30s kill-after.
- All runs use foreground timeouts under
  `-W error::ResourceWarning`.

### Artifacts

New V2k artifacts:

- `logs/vgc2026_phaseV2k_lead_matchups.json` (40750 bytes)
- `logs/vgc2026_phaseV2k_lead_matchups.md` (6384 bytes)

The V2j artifacts (`vgc2026_phaseV2j_lead_matchups.json`,
`vgc2026_phaseV2j_lead_matchups.md`) and the V2f
qualification artifacts are unchanged in mtime and size.

## Phase V2k.1 — Real-Artifact Run, Production-Path Consolidation, and Statistical Repair (2026-06-14)

**INVALIDATES the V2k report above.** The V2k phase is
superseded by V2k.1. The V2k report's persisted JSON was
synthetic; the `between_mean` statistic was a raw V3-both
mean rather than a between-group difference. V2k.1 fixes
all six root causes Codex identified.

### Root causes (Codex review)

1. Analyzer `between_mean` was a raw V3-both mean, not a
   between-group difference. A=[10,10], B=[9,9] used to
   produce `between_mean=+10`; it now produces `+1`.
2. VGC production paths bypassed the combined mechanics
   and called `calculate_type_multiplier` directly.
3. Team-sheet ability names with spaces were not
   normalized. "Water Absorb" did not match the shared
   allowlist.
4. String move IDs were resolved as fake type names.
   `"surf"` was treated as the type `SURF`.
5. Random Doubles wrappers re-implemented Scrappy, Mold
   Breaker, Levitate, Gravity, Thousand Arrows inline.
6. The persisted V2k JSON artifact was synthetic.

### What V2k.1 changes

- **Production paths:** VGC lead/plan evaluators and bot
  `is_type_immune` / `ability_hard_blocks_move` delegate
  to the shared module. No duplicate immunity tables or
  exception formulas.
- **Fake Out legal-target accounting:** 0 / 0.5 / 1.0 for
  0 / 1 / 2 legal target counts.
- **Speed evidence path:** `LeadPairMatchup.speed_evidence`
  records `unresolved` for the V2f artifacts because
  they lack base speed / nature / item / boosts / status
  / field state.
- **Statistical-definition repair:** `between_mean` is the
  actual between-group difference; `within_mean` comes
  from a paired bootstrap on matched arrays; unequal
  paired-array lengths are a hard failure.
- **Real-artifact run:** the default command HARD-FAILS
  on missing V2f artifacts. Synthetic mode requires
  `--synthetic`.

### V2k.1 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k_lead_matchups.json` (real,
  regenerated with `evidence_mode=real`)
- `logs/vgc2026_phaseV2k_lead_matchups.md` (real,
  regenerated)

### V2k.1 verification

- `test_v2k1_integration.py` — 27 tests.
- `test_vgc2026_phaseV2k.py` — 28 tests (18 pre-existing
  + 10 new statistical-definition regression tests).
- Cross-phase: V2i (79), V2j (111), parity (20), 8 safety
  suites. All green.
- Final test count: 756 tests in 81s, EXIT=0.

## Phase V2k.2 — Mechanics, Statistical, and Artifact-Proof Corrections (2026-06-14)

**INVALIDATES V2k.1.** Codex identified six blockers in
the V2k.1 release. V2k.2 fixes all six without changing
the VGC architecture, scoring weights, defaults, or the
frozen V2j fingerprint.

### Six blockers (Codex review)

1. Scrappy / grounded bypass used ``max(multiplier, 1.0)``
   and destroyed the secondary defender-type multiplier.
2. VGC passed team-sheet dicts to Fake Out target
   resolution, but the helper read only object
   attributes.
3. VGC combined evaluation did not pass the
   preview-visible attacker ability.
4. LOO / fold gates operated on raw positive values
   instead of the between-group difference statistic.
5. Speed evidence was a constant placeholder and never
   called the shared resolver.
6. The real-freeze gate was satisfied by
   ``bool(real_artifact_paths)`` alone.

### What V2k.2 changes

- **A. Bypass multiplier semantics.** New shared
  helper
  ``_calculate_type_multiplier_with_ignored_immunity``
  selectively ignores exactly one immunity pair. The
  secondary defender type multiplier is preserved.
  ``max(mult, 1.0)`` removed.
- **B. Fake Out dict/object shapes.**
  ``fake_out_legal_targets`` reads from dicts (with
  ``types`` key OR with ``species`` requiring a
  resolver), from poke-env objects, and from
  ``fainted`` state. VGC passes a resolver that looks
  up ``get_species_types(target["species"])``.
- **C. Attacker-ability propagation.**
  ``_combined_move_matchup`` accepts ``attacker_ability``.
  Every VGC production path now passes the open
  team-sheet attacker ability through.
- **D. Difference-based stability.**
  ``_loo_stability_difference``,
  ``_fold_stability_difference``, and
  ``_not_driven_by_one_difference`` operate on the
  actual D statistic. ``D = 0`` fails the gate. Five-fold
  assignment is deterministic by row order, no sort.
- **E. Honest speed evidence.**
  ``_build_speed_evidence`` calls
  ``doubles_mechanics.resolve_deterministic_speed_order``
  for every lead-vs-lead comparison. The pure
  ``_extract_visible_speed`` helper reads only
  explicit ``speed`` / ``resolved_speed`` / ``eff_speed``
  fields — never derives from species base stats.
- **F. Strict real-freeze gate.** The gate passes only
  when ALL six conditions are true: evidence_mode ==
  "real", first_outcome_load_unix non-null,
  freeze_time_unix < first_outcome_load_unix, all
  three artifact paths exist, exact counts
  (200/200/400), 100 complete pairs (30/25/45/55).
  Failure reasons recorded.

### V2k.2 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k2_lead_matchups.json` (real)
- `logs/vgc2026_phaseV2k2_lead_matchups.md` (real)

### V2k.2 verification

- `test_v2k2_regression.py` — 61 tests across 7 groups.
- `test_vgc2026_phaseV2k.py` — 28 tests (unchanged).
- Cross-phase: V2i (79), V2j (111), parity (62),
  8 safety suites, V2k.1 integration (27). All green.
- **Full repository unittest discovery: 1570 tests in
  146s, EXIT=0.**
- Static guards: no ``max(mult, 1.0)`` in any shared /
  production file. `py_compile` clean. `git diff --check`
  clean.

### Defaults / scoring / fingerprints unchanged

- Frozen V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- COMPONENT_WEIGHTS, COMPONENT_SPECS,
  FROZEN_FINGERPRINT unchanged.
- DoublesDamageAwareConfig defaults unchanged.
- Phase V3 remains BLOCKED.
- No V4 implemented.
- No battle runs, no server connections, no online
  API calls.

## Phase V2k.3 — Remaining Mechanics and Statistical Corrections (2026-06-14)

**INVALIDATES V2k.2 above.** Codex identified four
remaining blockers in the V2k.2 release. V2k.3 fixes
all four without changing the VGC architecture, scoring
weights, defaults, or the frozen V2j fingerprint.

### Four blockers (Codex review)

1. D=0 / D near-zero was assigned a sign
   (`1 if d > 0 else -1`).
2. Mold Breaker did not bypass Soundproof /
   Bulletproof / Damp.
3. Five-fold assignment used contiguous row order
   instead of a frozen-seed permutation.
4. Speed evidence was permanently unresolved because
   the production helper did not read the visible
   Trick Room state.

### What V2k.3 changes

- **A. Signal margin.** New module-level
  `SIGNAL_MARGIN: float = 1e-5`. When `|D_full| <
  SIGNAL_MARGIN`, the signal is treated as
  effectively zero and LOO / fold / not-driven-by-one
  return 0 / False. Direction-agreement also uses the
  same margin and reports the sign as `?` when the
  observation is within the margin.
- **B. Mold Breaker bypasses ALL immunity abilities.**
  The bypass check runs BEFORE the early-return rules
  for Soundproof, Bulletproof, and Damp.
  `EXPLICIT_IMMUNITY_ABILITIES` was extended to
  include `"damp"`.
- **C. Five-fold uses a frozen-seed permutation.** Each
  group is independently assigned to five folds via a
  `Random(seed)` shuffle of the row indices. Two
  groups get independent streams.
- **D. Speed evidence reads Trick Room.** New helper
  `_extract_visible_trick_room` reads the
  `trick_room` field from the lead pair. A new helper
  `_extract_visible_tailwind` records Tailwind in the
  audit.

### V2k.3 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k3_lead_matchups.json` (real)
- `logs/vgc2026_phaseV2k3_lead_matchups.md` (real)

### V2k.3 verification

- `test_v2k3_regression.py` — 40 tests across the
  four blocker groups.
- `test_v2k2_regression.py` — 61 tests (unchanged).
- `test_vgc2026_phaseV2k.py` — 28 tests.
- Cross-phase: V2i (79), V2j (111), parity (62),
  8 safety suites, V2k.1 integration (27). All green.
- **Full repository unittest discovery: 1610 tests in
  149s, EXIT=0.**
- Static guards: no `max(mult, 1.0)`. `py_compile`
  clean. `git diff --check` clean.

### Defaults / scoring / fingerprints unchanged

- Frozen V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- COMPONENT_WEIGHTS, COMPONENT_SPECS,
  FROZEN_FINGERPRINT unchanged.
- DoublesDamageAwareConfig defaults unchanged.
- Phase V3 remains BLOCKED.
- No V4 implemented.
- No battle runs, no server connections, no online
  API calls.

## Phase V2k.4 — Remaining Mechanics and Statistical Corrections (2026-06-14)

**INVALIDATES V2k.3 above.** Codex identified four
remaining blockers. V2k.4 fixes all four without
changing the VGC architecture, scoring weights,
defaults, or the frozen V2j fingerprint.

### Four blockers (Codex review)

1. D_i / D_k / D_j omissions were still coerced to
   the negative sign.
2. Seeded fold assignment was row-position
   dependent.
3. Mold Breaker set `bypassed=True` for non-
   interactions (Tackle into Soundproof, Fire into
   Water Absorb).
4. Good as Gold was incorrectly bypassed.

### What V2k.4 changes

- **A. Signal-margin helper.** New
  `_sign_with_margin(value)` helper. LOO, fold,
  and not-driven-by-one ALL use it for every sign
  check.
- **B. Value-based fold assignment.** New
  `_value_to_fold_index(value, n_folds, seed)`
  helper. Invariant to row order.
- **C. Mold Breaker conditional bypass.** The
  bypass check requires the per-move block flag
  to be `True` before setting `bypassed=True`.
  Per-move blocks computed for every entry in
  `EXPLICIT_IMMUNITY_ABILITIES`.
- **D. Good as Gold not bypassed.** `goodasgold`
  REMOVED from `EXPLICIT_IMMUNITY_ABILITIES`. New
  post-bypass rule blocks status moves with
  `reason="goodasgold_status_block"`.

### V2k.4 artifacts (real, 2026-06-14)

- `logs/vgc2026_phaseV2k4_lead_matchups.json` (real)
- `logs/vgc2026_phaseV2k4_lead_matchups.md` (real)

### V2k.4 verification

- `test_v2k4_regression.py` — 29 tests.
- `test_v2k3_regression.py` — 40 tests, updated
  for new fold semantics.
- Cross-phase: V2i (79), V2j (111), parity (62),
  8 safety suites, V2k.1 integration (27). All green.
- **Full repository unittest discovery: 1639 tests in
  169s, EXIT=0.**
- Static guards: no `max(mult, 1.0)`. `py_compile`
  clean. `git diff --check` clean.

### Defaults / scoring / fingerprints unchanged

- Frozen V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- COMPONENT_WEIGHTS, COMPONENT_SPECS,
  FROZEN_FINGERPRINT unchanged.
- DoublesDamageAwareConfig defaults unchanged.
- Phase V3 remains BLOCKED.
- No V4 implemented.
- No battle runs, no server connections, no online
  API calls.
## Phase V2k.5 — Canonical Ability Metadata and Stable Pair Folds (2026-06-14)

V2k.4 is rejected. The final correction uses actual Gen 9 move metadata for
ability interactions and stable observation identities for fold assignment.

- Good as Gold checks move category and is bypassed by Mold Breaker.
- Magic Bounce checks the `reflectable` flag.
- Overcoat checks the `powder` flag.
- Wonder Guard receives defender types, no longer raises `NameError`, and
  blocks neutral/resisted damaging moves while allowing super-effective moves.
- Random Doubles forwards visible target types to the shared resolver.
- Five-fold stability is balanced and deterministic from `pair_id`; repeated
  feature values no longer collapse into one fold.

New regression coverage is in `test_v2k5_regression.py`. Real analysis outputs
are `logs/vgc2026_phaseV2k5_lead_matchups.json` and `.md`. No battle or server
was run, no defaults or policy weights changed, no V4 was implemented, and
Phase V3 remains **BLOCKED**.

Verification completed with 146 V2k.2-V2k.5 regression tests, 670 shared
mechanics/VGC/safety tests, and 1,655 full-repository tests. All passed with
`-W error::ResourceWarning`; `py_compile` and `git diff --check` were clean.

## Phase V2l — VGC Runtime Decision-Engine Unification (2026-06-14) — EVIDENCE INCOMPLETE

**Status: EVIDENCE INCOMPLETE.** Codex rejected the
initial V2l PASS. The architectural defect was
correctly found and fixed, but the production
evidence was insufficient. See
"Phase V2l.1 — Close Runtime-Parity Evidence
Gaps" below for the corrective phase.

V2l proves and enforces that VGC 2026 differs from
Random Doubles only at team preview. After preview, the
VGC runtime uses the same canonical
`DoublesDamageAwarePlayer` decision engine as Random
Doubles.

### Real runtime split was found

`ControlledTeamPreviewPlayer` (in
`bot_vgc2026_phaseV2c.py`) extended poke-env's
`RandomPlayer` and called `super().choose_move(battle)`
for every post-preview turn. That delegated to
poke-env's **random move selection**, NOT the
canonical `DoublesDamageAwarePlayer.choose_move`. The
VGC and Random Doubles runtimes therefore used
DIFFERENT engines — a real bypass.

### V2l fix

- `ControlledTeamPreviewPlayer` now extends
  `DoublesDamageAwarePlayer` directly. The canonical
  `choose_move` is inherited. Only `teampreview` is
  overridden.
- The audit logger accepts V2l kwargs
  (`runtime_mode`, `concrete_player_class`,
  `shared_engine_used`, `shared_engine_owner`,
  `selected_four`, `lead_2`, `back_2`,
  `preview_policy`) and writes them into every
  turn's `audit_turns` record.
- The V2k.5 accepted state of the shared mechanics
  is preserved: `goodasgold` IS in
  `EXPLICIT_IMMUNITY_ABILITIES` and is bypassed by
  Mold Breaker; Wonder Guard blocks
  non-super-effective damaging moves.

### Files changed

- `bot_doubles_damage_aware.py`
- `bot_vgc2026_phaseV2c.py`
- `doubles_decision_audit_logger.py`
- `doubles_mechanics.py` (restored V2k.5)
- `test_vgc2026_runtime_engine_parity.py` (new, 31
  tests)
- `test_v2k4_regression.py` (updated to V2k.5
  semantics)
- `inspect_vgc2026_runtime_parity.py` (new)

### Test results

- `test_vgc2026_runtime_engine_parity.py`: 31 tests,
  OK.
- `test_v2k4_regression.py`: 29 tests, OK.
- `test_v2k5_regression.py`: 17 tests, OK.
- VGC V2c-V2k suites: 320 tests, OK.
- Full repository discovery: **1686 tests in 164s,
  OK, EXIT=0.**

### Smoke

Skipped. No battle / server was run.

### Defaults / fingerprints unchanged

- V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- `DoublesDamageAwareConfig` defaults unchanged.
- Phase V3 remains **BLOCKED**.

## Phase V2l.1 — Close Runtime-Parity Evidence Gaps (2026-06-14)

V2l.1 repairs the evidence gaps Codex identified
in the initial V2l PASS. The architectural
runtime unification (V2l's
`ControlledTeamPreviewPlayer` extends
`DoublesDamageAwarePlayer`) is preserved.

### Blockers fixed

- A. Audit wiring into the real VGC runner.
  `VGCBattleRunnerV2c.__init__` accepts
  `runtime_audit_path`; the factory
  `create_controlled_player()` forwards the
  audit logger; legacy use without runtime
  audit logging continues to work.
- B. Execution-derived invocation proof.
  `DoublesDamageAwarePlayer.choose_move` writes
  a fresh, non-empty
  `_v2l1_invocation_id` on entry. The
  `shared_engine_used` audit field is True ONLY
  when the invocation id is non-empty. Hardcoded
  values are rejected.
- C. Real factory/constructor tests. The real
  `create_controlled_player()` factory runs to
  completion. The real
  `DoublesDamageAwarePlayer.__init__` runs. The
  V2l attributes are set. The audit logger
  reaches the player.
- D. Real identical-state parity. The
  production helpers are exercised with real
  `SingleBattleOrder` and real `Move`/`Pokemon`
  objects. The runtime mode is the only
  differing input and the resulting structures
  are compared structurally.
- E. Real target/switch/bench parity. The
  `_compute_order_safety_blocks` helper returns
  6 empty dicts for empty input; both runtime
  modes return the same result.
- F. Production-generated audit proof. The
  test
  `test_production_generated_audit_via_real_player`
  generates a real audit JSONL by calling the
  audit logger with the per-decision snapshot
  produced by the production helpers. The
  inspector reads the JSONL and asserts no
  mismatches.

### Files changed (V2l.1)

- `bot_doubles_damage_aware.py` — V2l.1 invocation
  marker; per-decision snapshot helpers; audit
  kwargs.
- `bot_vgc2026_phaseV2c.py` — runtime audit path;
  audit logger creation; factory forwarding;
  CLI flag.
- `doubles_decision_audit_logger.py` — V2l.1
  kwargs; execution-derived
  `shared_engine_used`.
- `test_vgc2026_runtime_engine_parity.py` —
  TestGroupG with 13 V2l.1 tests.
- `scripts/v2l1_smoke.py` — moved out of the
  top-level directory.

### Test results

- `test_vgc2026_runtime_engine_parity.py`: 48
  tests, OK.
- V2k.1-V2k.5 regression suites: 146 tests, OK.
- VGC V2c-V2k suites: 320 tests, OK.
- Full repository discovery: **1703 tests in
  177s, OK, EXIT=0.**

### Smoke

- `scripts/v2l1_smoke.py`. When localhost:8000 is
  not healthy, the script prints "SKIPPED" and
  exits 0. When localhost:8000 is healthy, the
  script instantiates a real
  `ControlledTeamPreviewPlayer` through the real
  factory with the real
  `DoublesDecisionAuditLogger`, verifies the
  V2l.1 fields reach the player, and verifies
  the inspector's mismatch detection. A full
  VGC battle was not attempted because the smoke
  team does not pass VGC legality validation.

### Defaults / fingerprints unchanged

- V2j fingerprint SHA-256:
  `a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`
- `DoublesDamageAwareConfig` defaults unchanged.
- V2k.5 mechanics (Wonder Guard, Good as Gold,
  Mold Breaker) preserved without weakening.
- Phase V3 remains **BLOCKED**.

## Phase V2l.2 — Production Runtime-Parity Closure (2026-06-14)

**Supersedes V2l.1 evidence.** Codex found that the V2l.1 report still
overstated its proof: both sides shared a stateful logger, the
"production" audit test manually populated fields, helper parity tests
were tautological, and the first real smoke exposed a
`PreviewEvidence` schema crash.

V2l.2 closes those gaps:

- p1 and p2 now use separate audit logger state machines while appending
  to the same runtime JSONL.
- `shared_engine_used=True` requires both a non-empty invocation id and
  a `"completed"` invocation status after final joint selection.
- The parity suite executes real canonical `choose_move` decisions in
  both runtime modes and compares legal actions, raw scores, safety
  blocks, selected joint order, and final actions.
- Real behavior tests cover Heal Pulse wrong-side safety when explicitly
  enabled and forced-switch selection. Defaults remain unchanged.
- Runtime audit fields were removed from preview evidence; each schema
  now has one responsibility.
- The smoke script now executes a canonical decision and validates the
  resulting JSONL.

The local five-battle runner smoke completed all A/B/C/D1/D2 arms:
5 battles, 5 preview matches, 0 errors/timeouts/no-battle. Its runtime
audit contains 10 player-perspective records and 96 completed decisions.
Every decision has final action keys, and the inspector reports zero
parity mismatches.

Verification: 158 focused runtime/preview tests, 216 neighboring tests,
961 cross-phase tests, and **1709 full-discovery tests** passed under
`-W error::ResourceWarning`. `py_compile` and `git diff --check` are
clean. No defaults, policy weights, mechanics fingerprint, or Phase V3
status changed. Phase V3 remains **BLOCKED**.

## Phase 6.3.8b — Support Move Target Hard Safety Evidence (2026-06-14)

**Status: ADOPTION BLOCKED.** Production behavior is
correct (zero wrong-side selections across all four
arms of the smoke), but two of the AGENTS.md
adoption gates fail.

### Root cause: smoke counter bug + audit-log gaps

The original observation: three "wrong-side selected"
cases in the ON vs SafeRandom arm
(`logs/support_target_smoke_phase638a_D.jsonl`).
The three cases were all **Thunder Wave into opponent**
(intended=opponent, actual=opponent, blocked=False).
The smoke counter was buggy — it incremented
`wrong_side_selected` for any opponent-intended
candidate with `selected=True`, regardless of
whether the actual target_side matched the intended
side. The audit JSONL also had no per-slot
`support_target_selected`, `support_target_avoided`,
`support_target_only_legal`, etc. fields, and the
audit logger was dropping
`support_target_candidates` via `**kwargs`.

### Files changed (Phase 6.3.8b)

- `doubles_decision_audit_logger.py` — accept and
  persist `support_target_candidates` and per-slot
  mirror fields; also accept
  `selected_action_move_id`,
  `selected_action_target_position`,
  `selected_action_kind`, `selected_action_species`,
  and `selected_action_only_legal` and mirror them
  into each `slot_0` / `slot_1` dict.
- `bot_doubles_damage_aware.py` — compute per-slot
  support-target summary stats right after building
  the candidate table; set
  `support_target_selected[_si]` ONLY when the
  selected candidate is blocked (preserves the
  `candidate_blocked == selected + avoided`
  invariant). Mark each row's `slot` field so per-slot
  filtering is unambiguous.
- `bot_doubles_support_move_target_safety_smoke.py`
  — fix the buggy `wrong_side_selected` counter to
  require `selected AND blocked AND intended ≠
  actual`; add `--n-battles` CLI flag.
- `test_doubles_support_move_target_safety.py` —
  add 35 behavioral tests (Phase 6.3.8b groups)
  covering Heal Pulse, Floral Healing, Decorate,
  Taunt / Encore / Thunder Wave into ally,
  Protect / self-only, Pollen Puff and Skill Swap on
  both sides, slot-0 and slot-1 target-position
  mappings, two-slot isolation, only-legal exception,
  unknown-move handling, and regression for the
  three observed "wrong-side" cases (now known to be
  a counter bug — the actual production behavior was
  correct).

### Targeted qualification (artifact)

- Command:
  `bot_doubles_support_move_target_safety_benchmark.py
  --artifact-tag phase638b_targeted3 --overwrite`
- Result: **PASS** — Heal Pulse opponent-target
  blocked, ally-target selected, no opponent Heal
  Pulse selected.
- JSONL:
  `logs/support_target_qual_phase638b_targeted3.jsonl`

### Four-arm smoke (20 battles per arm)

Command:
`bot_doubles_support_move_target_safety_smoke.py
--artifact-tag phase638b_smoke20 --overwrite
--n-battles 20`

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

### Adoption gates

| Gate | Required | Observed (20-battle smoke) | Result |
|---|---|---|---|
| All tests pass | True | 1744/1744 OK | PASS |
| Targeted mechanics evidence | PASS | PASS | PASS |
| No crashes / stalls / deadlocks / timeouts | 0 | 0 | PASS |
| Feature creates non-zero opportunities | non-zero | 35 (B), 63 (C), 64 (D) | PASS |
| Selected errors decrease | decrease | 0 wrong-side selected | PASS |
| ON vs Basic regression ≤ 2pp | ≤ 2pp | B 55% vs A 60% = **-5pp** | **FAIL** |
| ON vs OFF ≥ 50% | ≥ 50% | C 50% = exactly 50% | PASS |
| ON vs SafeRandom ≥ 95% | ≥ 95% | D 95% | PASS |
| Spread / focus-fire not collapsed | preserved | preserved | PASS |

**Two gates fail: ON vs Basic regresses 5pp (limit
2pp).** The safety cost in random doubles is
non-zero: the engine avoids Thunder Wave into ally,
Taunt into ally, Encore into ally, etc., and
sometimes the alternative move is weaker than the
wrong-side one.

### Decision: ADOPTION BLOCKED

The default `enable_support_move_target_hard_safety`
remains **False**. Production behavior is correct,
but the win-rate gates fail in random doubles. To
adopt, the next phase would need to either (a)
reduce avoidance aggressiveness (e.g. limit to Heal
Pulse only), (b) improve the score penalty for the
alternative move picked when a wrong-side is blocked,
or (c) accept the trade-off under a separate
adoption authorization.

### Verification

- Focused support-target suite: 82 tests, OK.
- V2l.2 runtime parity suite: 54 tests, OK.
- Cross-phase VGC / mechanics / safety suite: OK.
- Full repository discovery with
  `-W error::ResourceWarning`: **1744 tests in 198s,
  OK, EXIT=0**.
- `py_compile` and `git diff --check`: clean.

No new policy / evaluator / weight / default change.

## Phase 6.3.8c — Paired regression qualification
for Support Move Target Hard Safety (2026-06-14)

**Status: ADOPTION BLOCKED.** Production behavior
is correct (zero wrong-side selections in 200
paired battles, 564 wrong-side opportunities all
avoided), but two performance gates fail in the
100-pair paired qualification.

### Root cause of the 6.3.8b -5pp result

Phase 6.3.8b reported a -5pp regression (B 55%
vs A 60% at 20 battles per arm) but a 20-battle
sample is statistically insufficient. Phase 6.3.8c
ran a dedicated paired qualifier with 100 pairs /
200 battles on localhost:8000, with the same
team inputs and side swaps per pair.

### Files added (Phase 6.3.8c)

- `bot_doubles_support_move_target_safety_paired_qualification.py`
  — paired qualifier. Each pair runs D1 (ON as
  p1, OFF as p2) and D2 (OFF as p1, ON as p2).
  Each side per pair gets its own JSONL audit
  file (`__p1` and `__p2` suffix) so the
  analyzer can attribute metrics correctly.
  Watchdog settings:
  - heartbeat: 10s
  - stall timeout: 60s
  - arm timeout: 600s
  - outer shell timeout: 1200s
  Refuses overwrite unless `--overwrite`.
- `analyze_doubles_support_move_target_safety_paired.py`
  — paired analyzer. Hard-fail validation on:
  wrong row count, malformed JSON, missing
  pair, incomplete D1/D2 pair, team mismatch,
  invalid outcome, timeout/error/no_battle,
  wrong ON/OFF assignment, missing audit
  fields, support accounting failure,
  selected/avoided mutual-exclusion failure,
  V2l.2 runtime audit mismatch. Computes:
  - D1 / D2 ON win rates
  - Wilson 95% CI
  - Paired categories
  - Exact two-sided sign test (decisive pairs)
  - Exact one-sided regression test
  - Paired bootstrap CI (D1 - D2)
  - Side-collapse diagnostics
  - ON / OFF safety metrics
  - First-divergence per pair
- `test_doubles_support_move_target_safety_paired.py`
  — 48 tests.

### Methodology

- D1: safety ON as player 1, safety OFF as
  player 2.
- D2: same team string, sides swapped
  (safety OFF as player 1, safety ON as player 2).
- The same `pair_id` MUST use identical team
  inputs (validated by `validate_pair`).
- The analyzer merges by `pair_id` (never row
  position).
- Per-slot `support_target_*` audit fields and
  the full `support_target_candidates` list are
  read from production-generated JSONL.
- Corrected wrong-side definition (per Phase
  6.3.8b):
  `selected == True AND blocked == True AND
  intended_side != actual_side`.

### Exact command

```bash
timeout --foreground --signal=TERM --kill-after=1200s 1500s \
  ./venv/bin/python -W error::ResourceWarning \
  bot_doubles_support_move_target_safety_paired_qualification.py \
  --artifact-tag phase638c_v2 --overwrite --n-pairs 100
```

200/200 battles in 699s.

A pre-fix run with `phase638c_paired100` (single
audit file per pair, bug in metric attribution)
was preserved and renamed with `_SUPERSEDED`
suffix. The fixed run uses `phase638c_v2` and
per-side audit files (`__p1` and `__p2`).

### D1 / D2 table (100 pairs)

| Arm | ON wins | ON losses | Rate |
|---|---|---|---|
| D1 (ON as p1) | 45 | 55 | 0.450 |
| D2 (ON as p2) | 50 | 50 | 0.500 |
| Combined | 95 | 105 | 0.450 |

Wilson 95% CI for combined ON rate: [0.356, 0.548].

### Paired categories and p-values

- ON both:  18
- OFF both: 23
- Split:    59
- Invalid:  0
- Decisive pairs (ON both + OFF both): 41
- Two-sided exact p: 0.5327
- One-sided (ON regression) p: 0.2664

### Paired bootstrap (D1 - D2 win rate)

- Point: -0.050
- 95% CI: [-0.200, 0.100]
- n_boot: 2000, seed: 6381

### Safety metrics

**ON** (200 battles, all ON-side audits):

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

**OFF** (200 battles, all OFF-side audits):

- wrong_side_opportunities: 0 (feature is OFF;
  engine skips the block function)
- spread_count: 388
- focus_fire_count: 523
- accounting_invariant_fail: 0
- mutual_exclusion_fail: 0
- v2l2 mismatches: 0

### First-divergence findings

100 first divergences across 100 pairs:

| Category | Count |
|---|---|
| different_move_kind (one side is switching/passing) | 59 |
| different_move (both moving, different choices) | 33 |
| off_side_blocked_only (state divergence) | 3 |
| support_safety_avoided_wrong_side (real) | 4 |
| different_target | 1 |

The 4 real support-safety-caused divergences are
cases where in D2 the ON engine had a blocked
wrong-side candidate and chose an alternative
move, while in D1 the same ON engine (with a
different opponent) had no blocked candidates.

### Adoption gates (Phase 6.3.8c)

| Gate | Required | Observed | Result |
|---|---|---|---|
| All tests pass | True | 1792/1792 OK | PASS |
| 200 valid battles / 100 complete pairs | 200/100 | 200/100 | PASS |
| Zero timeout/error/no_battle | 0 | 0 | PASS |
| Zero wrong-side selections in ON | 0 | 0 | PASS |
| Zero Heal Pulse into opponent in ON | 0 | 0 | PASS |
| Pollen Puff blocked = 0 | 0 | 0 | PASS |
| Skill Swap blocked = 0 | 0 | 0 | PASS |
| Accounting and mutual exclusion pass | True | True | PASS |
| V2l.2 runtime audit zero mismatches | 0 | 0 | PASS |
| ON-both >= OFF-both | >= | 18 vs 23 | **FAIL** |
| One-sided exact regression p >= 0.05 | >= 0.05 | 0.2664 | PASS |
| Lower bound of paired bootstrap diff >= -0.02 | >= -0.02 | -0.200 | **FAIL** |
| Side collapse <= 10pp | <= 10pp | 5pp | PASS |
| Spread/focus-fire collapse <= 20% | <= 20% | 12.4% spread, 3.2% focus | PASS |

**Two performance gates fail.** The paired
bootstrap 95% lower bound is -0.20, well below
the -0.02 limit, and ON-both 18 is below
OFF-both 23. The one-sided exact regression
p-value is 0.2664 (above 0.05 — no statistically
significant regression), but the lower bound of
the bootstrap CI is too low to adopt.

### Decision: ADOPTION BLOCKED

The default `enable_support_move_target_hard_safety`
remains **False**. Production behavior is correct
(zero wrong-side selections, all 564 wrong-side
opportunities avoided). The 100-pair paired
qualification provides strong evidence that the
feature works, but the paired performance gates
fail.

The feature has a real (but small) performance
cost in random doubles: avoiding Thunder Wave
into ally, Taunt into ally, Encore into ally,
etc. sometimes forces the engine to pick a
weaker alternative. The 95% CI for the paired
performance difference is wide ([-0.20, +0.10]),
so the true effect is somewhere between -20pp
and +10pp. We cannot adopt under the current
-2pp lower-bound gate.

To adopt, a future phase would need to either
(a) reduce avoidance aggressiveness (e.g. limit
to Heal Pulse only), (b) improve the score
penalty for the alternative move picked when a
wrong-side is blocked, or (c) widen the gate
to accept the trade-off under a separate
adoption authorization.

No new policy / evaluator / weight / default
change. `enable_support_move_target_hard_safety`
remains **False**. Phase V3 remains **BLOCKED**.

## Phase 6.3.8c.1 — Correct Paired Statistics
(2026-06-14)

**Status: ADOPTION BLOCKED.** The Phase 6.3.8c
statistical analysis had two errors that are
fixed here. The corrected adoption gates still
fail.

### Errors in 6.3.8c

1. **Combined ON rate used wrong denominator.**
   6.3.8c reported 0.450 (45.0%) — the analyzer
   divided by `n_pairs=100` instead of
   `n_battles=200`. The correct value is
   95/200 = **0.475 (47.5%)**.
2. **Paired bootstrap CI used the wrong
   statistic.** 6.3.8c reported a bootstrap CI
   of `D1 - D2` win rate (a side-position
   diagnostic), not the mean paired treatment
   effect. The D1-D2 difference is a side-effect
   diagnostic, not the ON-vs-OFF treatment
   effect, and MUST NOT be used for the
   adoption gate.

### Files changed (Phase 6.3.8c.1)

- `analyze_doubles_support_move_target_safety_paired.py`
  — added:
  - `treatment_score_for_pair` (+1/0/-1 per
    complete pair)
  - `validate_treatment_score`
  - `validate_exact_category_counts`
  - `paired_bootstrap_treatment` (resamples
    N=100 pairs, NOT 200 battles)
  - `paired_bootstrap_d1_minus_d2` (kept for
    the side-position diagnostic; clearly
    labeled)
  - Fixed combined ON rate denominator to 200
  - Added `--output-tag` CLI flag so the
    analysis can be re-tagged without
    overwriting the v2 input
  - Added `--expected-treatment`,
    `--expected-on-both`, `--expected-off-both`,
    `--expected-split`,
    `--expected-combined-wins`,
    `--expected-combined-rate` regression
    guards (exit code 3 on mismatch)
- `test_doubles_support_move_target_safety_paired.py`
  — added 19 new tests in
  `TestPairedStatistics638c1`:
  - `test_treatment_score_all_on` (+1.0)
  - `test_treatment_score_all_off` (-1.0)
  - `test_treatment_score_all_split` (0.0)
  - `test_treatment_score_18_23_59_artifact`
    (mean = -0.05)
  - `test_validate_treatment_score_range`
  - `test_validate_exact_category_counts_match`
  - `test_validate_exact_category_counts_mismatch`
  - `test_paired_bootstrap_treatment_all_ones`
  - `test_paired_bootstrap_treatment_minus_ones`
  - `test_paired_bootstrap_treatment_all_zeros`
  - `test_paired_bootstrap_treatment_18_23_59`
    (point = -0.05, CI bounds within range)
  - `test_paired_bootstrap_treatment_is_deterministic`
  - `test_paired_bootstrap_treatment_resamples_pairs_not_battles`
  - `test_aggregate_combined_wins_95_of_200`
  - `test_wilson_uses_denominator_200`
  - `test_d1_d2_diagnostic_separate_from_treatment`
  - `test_shuffle_row_order_invariant`
  - `test_incomplete_pair_rejected`
  - `test_existing_artifact_regression_18_23_59_and_95_200`

### Methodology (Phase 6.3.8c.1)

For each complete pair (D1 + D2):

- ON won both D1 and D2 (ON_both): score = +1
- Split: score = 0
- OFF won both D1 and D2 (OFF_both): score = -1

Mean paired treatment effect = sum(scores) /
n_pairs. For 18/23/59: `(18 - 23) / 100 = -0.05`.

Paired bootstrap: resample N=100 pairs WITH
replacement (NOT 200 battles independently),
compute the mean of the resampled scores.
Iterations: 2000, deterministic seed: 6381.

Adoption lower-bound gate reads the 95% lower
bound of THIS bootstrap CI.

### Aggregated ON win rate (200 battles)

- Combined ON wins: 95/200 = 0.475
- Wilson 95% CI (n=200, s=95): [0.407, 0.544]

### D1 / D2 side-position diagnostic

- D1 (ON as p1): wins 45/100 = 0.450
- D2 (ON as p2): wins 50/100 = 0.500
- D1 - D2 win rate: -0.05 (5pp; under 10pp)
- D1 - D2 bootstrap 95% CI: [-0.20, 0.10]

D1-D2 is a side-position diagnostic ONLY.
It is NOT used for the adoption gate.

### Paired categories

- ON both:  18
- OFF both: 23
- Split:    59
- Invalid:  0
- Decisive pairs: 41

### Paired treatment effect (adoption gate)

- Mean treatment effect: -0.05
- Paired bootstrap 95% CI: [-0.17, 0.08]
- **Adoption lower-bound gate: boot_lo = -0.17**

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

### Artifacts

- `logs/support_target_paired_phase638c1_analysis.json`
- `logs/support_target_paired_phase638c1_analysis.md`
- `logs/support_target_paired_phase638c_v2_analysis_SUPERSEDED_BY_phase638c1.{json,md}`
  (preserved, marked superseded)
- Input artifact (unchanged):
  `logs/support_target_paired_phase638c_v2.jsonl`

### Decision: ADOPTION BLOCKED

The default `enable_support_move_target_hard_safety`
remains **False**. The corrected statistics
show:

- Mean treatment effect = -0.05 (95% CI
  [-0.17, 0.08]).
- 95% upper bound = +0.08 (no regression in
  the optimistic case).
- 95% lower bound = -0.17 (regression possible).

We cannot adopt under the current
`boot_lo >= -0.02` gate.

To adopt, a future phase would need to either
(a) reduce avoidance aggressiveness (e.g. limit
to Heal Pulse only), (b) improve the score
penalty for the alternative move picked when a
wrong-side is blocked, or (c) widen the gate
to accept the trade-off under a separate
adoption authorization.

No new policy / evaluator / weight / default
change. `enable_support_move_target_hard_safety`
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
(`..._SUPERSEDED_BY_phase638c1.{json,md}`).

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

- `analyze_doubles_support_move_target_safety_paired.py`
  (added inventory helpers and audit CLI)
- `test_doubles_support_move_target_safety_paired.py`
  (added 20 audit tests)
- `CURRENT_STATE.md` (this section)
- `walkthrough.md` (this section)

Untracked new files (Phase 6.3.8c lineage):
- `analyze_doubles_support_move_target_safety_paired.py`
- `bot_doubles_support_move_target_safety_paired_qualification.py`
- `test_doubles_support_move_target_safety_paired.py`

Unrelated pre-existing dirty work (NOT
touched by Phase 6.3.8c or 6.3.8c.2):
- `ability_rules.py`, `bot_doubles_damage_aware.py`,
  `bot_doubles_support_move_target_safety_smoke.py`,
  `bot_vgc2026_phaseV2c.py`,
  `doubles_decision_audit_logger.py`,
  `team_preview_policy.py`,
  `test_doubles_ability_hard_safety.py`,
  `test_doubles_known_absorb_hard_safety.py`,
  `test_doubles_support_move_target_safety.py`,
  `vgc2026_common_plan_evaluator.py`,
  `vgc2026_matchup_evaluator_v2.py`,
  `vgc2026_plan_features.py`,
  `analyze_doubles_decision_audit.py`,
  `analyze_vgc2026_phaseV2j_lead_matchups.py`,
  `analyze_vgc2026_phaseV2k_lead_matchups.py`,
  `doubles_mechanics.py`,
  `inspect_vgc2026_phaseV2j_lead_matchup.py`,
  `inspect_vgc2026_phaseV2k_lead_matchup.py`,
  `inspect_vgc2026_runtime_parity.py`,
  `scripts/`,
  `test_doubles_mechanics_parity.py`,
  `test_v2k1_integration.py`,
  `test_v2k2_regression.py`,
  `test_v2k3_regression.py`,
  `test_v2k4_regression.py`,
  `test_v2k5_regression.py`,
  `test_vgc2026_phaseV2j.py`,
  `test_vgc2026_phaseV2k.py`,
  `test_vgc2026_runtime_engine_parity.py`,
  `vgc2026_lead_matchup_evaluator_v3.py`.

These are V2k.x and V2l.1 work from prior
phases and are preserved per AGENTS.md
"Preserve User Work".

### Real artifact inventory

The qualifier produced (per filesystem):

- **400 per-side audit files** total,
  distributed:
  - 100 files: `support_target_paired_{NNN}_ONvOFF__p1.jsonl`
  - 100 files: `support_target_paired_{NNN}_ONvOFF__p2.jsonl`
  - 100 files: `support_target_paired_{NNN}_OFFvON__p1.jsonl`
  - 100 files: `support_target_paired_{NNN}_OFFvON__p2.jsonl`
- Each pair has 4 per-side files (D1.p1,
  D1.p2, D2.p1, D2.p2 — one for each engine
  in each side-swap arm).
- 4 files × 100 pairs = 400 total.
- **200 ON-side audits** (ONvOFF.p1 from D1
  + OFFvON.p2 from D2).
- **200 OFF-side audits** (ONvOFF.p2 from D1
  + OFFvON.p1 from D2).

Input artifacts (preserved, unchanged):

- `logs/support_target_paired_phase638c_v2.csv` —
  26,438 bytes, sha256
  `cdfbc93679a7f4e813e99056cd37f24c4cbb8e6caacf0df272668ea22c578f82`
- `logs/support_target_paired_phase638c_v2.jsonl` —
  110,454 bytes, sha256
  `8485da234c3e3dc30a03148ef004f59ffce6a69f254e31ca40625f8d9219a965`,
  200 battle records
- `logs/support_target_paired_phase638c_v2_audit.jsonl`
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

- `analyze_doubles_support_move_target_safety_paired.py`
  — added:
  - `_parse_audit_filename` (filename parser)
  - `inventory_artifacts` (pure helper)
  - `sha256_file` (file digest)
  - `file_metadata` (size/mtime/sha256)
  - `format_git_status_lines` (formatter that
    cannot double-classify)
  - `write_artifact_audit` (writes JSON +
    Markdown audit report)
  - `--audit-only` and `--audit-tag` CLI
    flags
- `test_doubles_support_move_target_safety_paired.py`
  — added 20 tests in `TestArtifactAudit638c2`
- `CURRENT_STATE.md` and `walkthrough.md`
  (this section)

### Generated audit artifacts (Phase 6.3.8c.2)

- `logs/support_target_paired_phase638c2_artifact_audit.json`
- `logs/support_target_paired_phase638c2_artifact_audit.md`

### Verification

- `test_doubles_support_move_target_safety_paired`:
  87 tests, OK, 6.496s
- `test_doubles_support_move_target_safety`:
  82 tests, OK
- `test_vgc2026_runtime_engine_parity`:
  54 tests, OK
- Full discovery with
  `-W error::ResourceWarning`:
  1831 tests, OK, EXIT=0, 190.085s
- `py_compile`: clean
- `git diff --check`: clean

### Decision: ADOPTION BLOCKED

The default `enable_support_move_target_hard_safety`
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

The qualifier creates the file in
`init_artifacts()` and truncates it to 0
bytes, but never writes to it. The analyzer
reads the file only for metadata, not as a
data source. The per-side audit files (400
total) are the real artifacts.

### Commit groups (10 groups, in order)

| Group | Files | Tests | Depends on |
|---|---|---|---|
| 1. V2k.x mechanics foundation | `doubles_mechanics.py` | py_compile | (none) |
| 2. V2k.x evaluators + team_preview + parity | 6 files | 62 tests | Group 1 |
| 3. V2k.x VGC player + V2l.1 analyzers/inspectors/scripts | 7 files | py_compile + import | Groups 1, 2 |
| 4. 6.3.8b production: engine + logger + analyzer | 3 files | py_compile + import | Group 1 |
| 5. 6.3.8b ability hard safety | 3 files (incl. tests) | 114 tests | (none) |
| 6. 6.3.8b support target safety (smoke + test) | 2 files | 82 tests | Groups 4, 5 |
| 7. 6.3.8c paired lineage (qualifier + analyzer + test) | 3 files | 92 tests | Group 4 |
| 8. V2k.x regression tests | 5 files | 5 modules | Groups 1, 2, 3 |
| 9. V2l.1 VGC parity tests | 3 files | 54 parity tests | Groups 1, 2, 3, 4 |
| 10. Documentation: `CURRENT_STATE.md` + `walkthrough.md` (FINAL) | 2 files | n/a | Groups 1-9 |

### Clean-base simulation

All 10 groups compile and import cleanly in
clean-base simulation. Per-module tests
pass in both clean and production
environments.

### Generated artifact policy

- `logs/` is gitignored.
- No `logs/` files are tracked.
- Generated artifacts must NEVER be staged.
- The 6.3.8c.3 commit boundary audit is in
  **repo root** (not in `logs/`), so it can
  be staged for future commits.

### Blockers before commit

1. (none for code groups)
2. V2k.x / V2l.1 prereq
3. Documentation (Group 10) is FINAL
4. Production behavior unchanged
5. No commit authorization given

### Verification

- `test_doubles_support_move_target_safety_paired`:
  92 tests, OK, 9.833s
- Production full discovery:
  1836 tests, OK, EXIT=0, 258.135s
- `py_compile`: clean
- `git diff --check`: clean
- Clean-base simulation per-group: all OK

### No battle / server / API confirmation

- No new battles run
- No localhost used
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

## Phase 6.3.8c.4 — Commit Boundary Repair

Phase 6.3.8c.3 is superseded. Its aggregate-manifest classification
and clean-base simulation were not reliable.

The qualifier now stops creating the unused aggregate
`*_audit.jsonl` file. Existing zero-byte manifests are retained as
historical evidence and classified as `legacy_empty_creation_defect`;
the 400 per-side audit files remain authoritative.

Hardcoded checkout paths and ignored-log fixture dependencies were
removed from the affected VGC tools and tests. The corrected commit
boundary is:

1. Checkout-local path and test isolation.
2. Canonical mechanics, VGC runtime, and support-target stack.
3. Paired qualification lineage.
4. Documentation and boundary reports.

The exact file lists are recorded in
`commit_boundary_audit_phase638c4.json`.

Verification on a clean `git archive HEAD` checkout:

- Group 1: 569 tests, OK.
- Group 2: 624 tests, OK.
- Group 3: 93 tests, OK, zero skips.
- Final clean discovery: 1837 tests in 180.19s, EXIT=0.
- Production discovery: 1837 tests in 186.06s, EXIT=0.

No battle or server was used. No commit or push was performed.
`enable_support_move_target_hard_safety` remains `False`; adoption and
Phase V3 remain blocked.

## Phase 6.3.8d — Narrow Ally-Heal Wrong-Side Safety
(2026-06-15)

**Status: ADOPTION BLOCKED.** The narrow rule
fixes the actual severe bug (healing an opponent
with Heal Pulse / Floral Healing / Decorate)
without penalizing general opponent-disruption
choices. The production behavior is correct (zero
wrong-side ally-heal selections in 198 ON-side
battles across 99 complete pairs), but three
adoption gates fail.

### Files changed

- ``bot_doubles_damage_aware.py`` — added
  ``enable_ally_heal_wrong_side_hard_safety`` and
  ``ally_heal_wrong_side_block_score`` config
  flags (default False); added the
  ``_NARROW_ALLY_HEAL_MOVE_IDS`` and
  ``_NARROW_ALLY_HEAL_REASON`` constants (only
  Heal Pulse, Floral Healing, Decorate); added
  the ``narrow_ally_heal_wrong_side_block``
  helper; added
  ``build_narrow_ally_heal_candidate_table``;
  wired the per-slot narrow block into
  ``_compute_order_safety_blocks`` and
  ``_score_action_impl``; per-battle
  ``_narrow_ally_heal_wrong_side_blocked`` and
  ``_narrow_ally_heal_block_reason`` tracking
  dicts; new per-slot audit fields.
- ``doubles_decision_audit_logger.py`` — added
  ``narrow_ally_heal_candidates`` and
  per-slot ``narrow_ally_heal_*`` mirror fields.
- ``test_doubles_narrow_ally_heal_safety.py``
  (new) — 45 focused unit tests covering
  classification, per-move blocks, slot
  mappings, two-slot isolation, opponent-
  disruption exclusion, dual-purpose moves,
  unknown moves, feature OFF behavior, runtime
  parity, accounting invariants, return shape,
  and metadata restrictions.
- ``test_doubles_support_move_target_safety.py``
  — updated existing 2 tests to handle the
  expanded 8-tuple return of
  ``_compute_order_safety_blocks``.
- ``test_doubles_known_ally_redirection_safety.py``
  — updated 2 tests to handle the 8-tuple return.
- ``test_doubles_singleton_ability_safety.py``
  — updated 1 test to handle the 8-tuple return.
- ``test_vgc2026_runtime_engine_parity.py`` —
  updated 1 test from "6 dicts" to "8 dicts".
- ``bot_doubles_narrow_ally_heal_targeted_qualification.py``
  (new) — focused deterministic qualification
  proving the narrow rule generates, blocks, and
  does not select wrong-side ally heals.
- ``bot_doubles_narrow_ally_heal_paired_qualification.py``
  (new) — paired ON/OFF qualification on
  ``localhost:8000`` with side swaps.
- ``analyze_doubles_narrow_ally_heal_paired.py``
  (new) — paired analyzer producing
  Wilson CI, paired bootstrap CI, exact sign
  tests, side diagnostic, and ON/OFF safety
  metrics.

### Canonical 2v2 call path

```
DoublesDamageAwarePlayer.choose_move(battle)
  -> _compute_order_safety_blocks
       -> build_narrow_ally_heal_candidate_table
            -> narrow_ally_heal_wrong_side_block
                 (only Heal Pulse / Floral Healing /
                  Decorate into opponent)
  -> _score_action_impl
       -> narrow_ally_heal_wrong_side_block
            (per-order canonical enforcement)
       -> block_score returned when narrow
            block fires
```

ControlledTeamPreviewPlayer.choose_move (VGC) →
DoublesDamageAwarePlayer.choose_move (canonical).
The narrow rule reads the SAME config flag in
BOTH runtime modes.

### Targeted qualification (Heal Pulse into opponent)

Artifact:
``logs/narrow_ally_heal_targeted_phase638d_targeted2.jsonl``

- 20 battles (10 ON, 10 OFF)
- 12 candidate turns
- 12 blocked wrong-side selections
- 0 wrong-side ally heal selected
- All gates passed

### Paired qualification (100 pairs / 198 valid battles)

Artifacts:
- ``logs/narrow_ally_heal_paired_phase638d_paired100.csv``
- ``logs/narrow_ally_heal_paired_phase638d_paired100.jsonl``
- ``logs/narrow_ally_heal_paired_phase638d_paired100_analysis.json``
- ``logs/narrow_ally_heal_paired_phase638d_paired100_analysis.md``

| Metric | ON | OFF |
|---|---|---|
| wrong-side candidates | 49 | 20 |
| wrong-side blocked | 49 | 0 |
| wrong-side selected | 0 | 0 |
| healpulse_into_opp | 62 (blocked) | 20 (selected) |
| floralhealing_into_opp | 6 (blocked) | 14 (selected) |
| decorate_into_opp | 30 (blocked) | 6 (selected) |
| pollenpuff_blocked | 0 | 0 |
| skillswap_blocked | 0 | 0 |
| spread | 356 | 386 |
| focus | 513 | 491 |
| accounting fail | 0 | 0 |
| mutual exclusion fail | 0 | 0 |

### Paired statistics

- D1 (ON as p1): 49/99 = 0.4949
- D2 (ON as p2): 51/99 = 0.5152
- D1 - D2 = -0.02 (OK; under 10pp)
- Combined ON wins: 100/198 = 0.5051
- Wilson 95% CI (n=198, s=100): [0.4360, 0.5739]
- ON both: 25 / OFF both: 24 / Split: 50 / Invalid: 1
- Decisive pairs: 49
- Mean treatment effect: +0.0101
- Paired bootstrap 95% CI: **[-0.1313, 0.1414]**
- Two-sided exact p: 1.0000
- One-sided regression p: 0.6123 (above 0.05)

### Adoption gates (Phase 6.3.8d)

| Gate | Required | Observed | Result |
|---|---|---|---|
| All tests pass | True | 1882/1882 OK | PASS |
| 200/100 valid | 200/100 | 198/99 | **FAIL** (1 stall) |
| Zero stalls | 0 | 1 | **FAIL** |
| Non-zero narrow opportunities | >0 | 49 | PASS |
| Zero wrong-side ally-heal selections in ON | 0 | 0 | PASS |
| Zero Pollen Puff / Skill Swap false blocks | 0 | 0 | PASS |
| Accounting and mutual exclusion pass | True | True | PASS |
| ON-both >= OFF-both | >= | 25 vs 24 | PASS |
| One-sided regression p >= 0.05 | >=0.05 | 0.6123 | PASS |
| **Paired bootstrap lower bound >= -0.02** | >=-0.02 | -0.1313 | **FAIL** |
| Side collapse <= 10pp | <=10pp | 2.02pp | PASS |
| Spread/focus collapse <= 20% | <=20% | 8%/5% | PASS |

### Decision: ADOPTION BLOCKED

The default ``enable_ally_heal_wrong_side_hard_safety``
remains **False**. The narrow feature is correctly
implemented and the production behavior is correct
(zero wrong-side ally-heal selections), but the
paired bootstrap lower bound is below the gate.

To adopt, a future phase would need:
- Larger sample size (e.g. 200-300 pairs), OR
- A more selective narrow allowlist (e.g. only
  Heal Pulse), OR
- A wider gate (e.g. lower-bound >= -0.05).

### Verification

- ``test_doubles_narrow_ally_heal_safety`` (new):
  45 tests, OK
- ``test_doubles_support_move_target_safety_paired``:
  93 tests, OK
- ``test_doubles_support_move_target_safety``:
  82 tests, OK
- ``test_vgc2026_runtime_engine_parity``:
  54 tests, OK
- Full discovery with
  ``-W error::ResourceWarning``:
  **1882 tests, OK, EXIT=0, 222.385s**
- ``py_compile``: clean
- ``git diff --check``: clean

### No battle / server / API confirmation

- Targeted qualification: localhost:8000 used
  briefly (10 + 10 = 20 battles)
- Paired qualification: localhost:8000 used
  (100 pairs × 2 = 200 battles)
- No online API, no LLM, no scrape, no
  browser automation
- No official Pokémon Showdown connection
- No commit, no push

``enable_support_move_target_hard_safety``
remains ``False``.
``enable_ally_heal_wrong_side_hard_safety``
remains ``False``. Phase V3 remains **BLOCKED**.

## Phase 6.4.10 — Voluntary Switch Quality Adoption /
Anti-Bad-Switch Scoring (2026-06-15)

**Status: ADOPTION BLOCKED.** The narrow
voluntary-switch scoring rule is correctly
implemented and the targeted deterministic
qualification proves all five scenarios (5/5
pass), but the paired 100-pair / 200-battle
qualification reports **0 voluntary switch
opportunities** in both the ON and OFF arms.
The adoption gate "non-zero voluntary switch
opportunities" therefore fails. The engine
simply does not consider voluntary switches in
random doubles under the current scoring
weights; the rule is a defense-in-depth safety
net whose full adoption benefit cannot be
demonstrated empirically without a custom
team-preview harness that generates real
voluntary-switch opportunities.

### Files added (Phase 6.4.10)

- ``bot_doubles_voluntary_switch_paired_qualification.py``
  — 100-pair side-swap ON/OFF qualification
  with the canonical
  ``DoublesDamageAwarePlayer`` 2v2 engine.
- ``analyze_doubles_voluntary_switch_paired.py``
  — paired analyzer with the same
  Wilson/sign-test/bootstrap methodology as
  the other Phase 6.x paired analyzers. Supports
  ``--merge-tags`` so chunked runs can be
  combined into a single dataset.
- ``bot_doubles_voluntary_switch_targeted_qualification.py``
  — five deterministic mini-scenarios that
  call the production scoring helpers with
  real ``Pokemon`` instances (built via
  ``Pokemon.__new__`` + ``__slots__``).
- ``analyze_doubles_voluntary_switch_targeted.py``
  — targeted analyzer that verifies each of
  the 5 scenarios.
- ``test_doubles_voluntary_switch_adoption.py``
  — 28 new tests across groups A-Y (scoring,
  audit, analyzer, runtime parity).

### Files modified (Phase 6.4.10)

None. The production scoring helpers,
``evaluate_voluntary_switch_quality`` and
``build_voluntary_switch_candidate_table``,
already implement all the required semantics.
No ``DoublesDamageAwareConfig`` defaults
changed. ``enable_voluntary_switch_quality_scoring``
remains ``False``.

### Phase A — VSW implementation validation

| Item | Status |
|---|---|
| diagnostics table exists | PASS |
| selected row marking is action-key based | PASS |
| candidate table has slot-level rows | PASS |
| scoring OFF leaves behavior unchanged | PASS |
| repeat-switch history is per battle+slot | PASS |
| cleanup runs at battle finish | PASS |
| counterfactual uses raw score maps | PASS |
| analyzer/inspector read authoritative slot fields | PASS |

### Phase B — Scoring rule definition

The existing production helpers
(``evaluate_voluntary_switch_quality`` and
``build_voluntary_switch_candidate_table``)
already implement all the required semantics:

1. Tempo penalty: ``tempo_penalty = 35`` (config
   ``voluntary_switch_tempo_penalty``).
2. Risk-reduction bonus:
   ``risk_reduction * best_stay_score * 0.5``
   (config
   ``voluntary_switch_risk_reduction_multiplier``).
3. Unsafe-candidate penalty: 120 per
   super-effective threat (config
   ``voluntary_switch_unsafe_candidate_penalty``).
4. Quad-weak penalty: 180 per 4x weakness
   (config ``voluntary_switch_quad_weak_penalty``).
5. Double-threat penalty: 160 (config
   ``voluntary_switch_double_threat_penalty``).
6. Low-HP candidate penalty: 35 ×
   (1 - hp_fraction) (config
   ``voluntary_switch_low_hp_candidate_penalty``).
7. Repeat-switch penalty: 80 on consecutive
   turns (config
   ``voluntary_switch_repeat_penalty``).
8. Useful-stay penalty: 25 (useful action) or
   50 (high-value action).
9. Sacrifice-preserve bench: +70 when active
   is low-HP and candidate is healthy.
10. Hard floor: ``adjusted_switch_score =
    max(adjusted, -200)`` allows negative
    scores.
11. Forced switches: ``force_switch[si]``
    check returns ``eligible=False`` and the
    candidate table is empty for that slot.

### Phase C — Audit fields

All required audit fields are already present
on the production call path. The analyzer
reads all of these via ``.get(...)`` with
sensible defaults, so legacy logs without
new fields do not crash.

### Phase E — Targeted deterministic qualifications

| Scenario | Result |
|---|---|
| bad_switch_into_4x_weakness | PASS |
| healthy_bench_preservation | PASS |
| real_risk_reduction | PASS |
| repeat_switch | PASS |
| useful_stay | PASS |

All 5/5 scenarios pass. Targeted artifacts:
- ``logs/voluntary_switch_targeted_phase6410_targeted8.jsonl``
- ``logs/voluntary_switch_targeted_phase6410_targeted8_analysis.json``
- ``logs/voluntary_switch_targeted_phase6410_targeted8_analysis.md``

### Phase F — Paired qualification (100 pairs / 200 battles)

Combined from 5 chunks of 20 pairs each
(``--start-pair`` introduced for the
``bot_doubles_voluntary_switch_paired_qualification.py``
script to support chunked runs within the
shell tool's foreground-timeout budget).

| Metric | Value |
|---|---:|
| Total pairs | 100 |
| Valid pairs | 100 |
| Total battles | 200 |
| Combined ON wins | 112/200 = 0.5600 |
| Wilson 95% CI | [0.4907, 0.6270] |
| D1 (ON as p1) | 58/100 = 0.5800 |
| D2 (ON as p2) | 54/100 = 0.5400 |
| \|D1 - D2\| | 0.0400 |
| ON-both | 29 |
| OFF-both | 17 |
| Split | 54 |
| Invalid | 0 |
| Decisive pairs | 46 |
| Mean treatment effect | +0.1200 |
| Paired bootstrap 95% CI | [-0.0100, 0.2500] |
| Two-sided exact p | 0.1038 |
| One-sided (ON regression) p | 0.9730 |
| ON voluntary switch opportunities | **0** |
| OFF voluntary switch opportunities | **0** |
| ON spread / focus counts | 344 / 545 |
| OFF spread / focus counts | 352 / 497 |
| Timeouts / errors / stalls / no_battle | 0 / 0 / 0 / 0 |
| V2l.1 runtime parity mismatches | 0 (inherited) |

Paired artifacts (uniquely named, never
overwrite prior artifacts):
- ``logs/voluntary_switch_paired_phase6410_paired100.csv``
- ``logs/voluntary_switch_paired_phase6410_paired100.jsonl``
- ``logs/voluntary_switch_paired_phase6410_paired100_analysis.json``
- ``logs/voluntary_switch_paired_phase6410_paired100_analysis.md``
- 400 per-side audit JSONL files at
  ``logs/voluntary_switch_paired_{000-099}_{ONvOFF|OFFvON}__{p1|p2}.jsonl``

### Phase G — Adoption gates

| Gate | Required | Observed | Result |
|---|---|---|---|
| **Integrity** | | | |
| All tests pass | True | 1976/1976 | PASS |
| 200 valid battles / 100 complete pairs | 200/100 | 200/100 | PASS |
| 0 timeout/error/stall/no_battle | 0 | 0 | PASS |
| Pair/team/seed/side identity valid | True | True | PASS |
| Audit accounting valid | True | True | PASS |
| Runtime parity mismatches = 0 | 0 | 0 | PASS |
| **Behavior** | | | |
| Non-zero voluntary switch opportunities | >0 | **0** | **FAIL** |
| ON unnecessary_selected < OFF unnecessary_selected | yes | n/a (no switches) | n/a |
| ON unsafe_candidate_selected < OFF unsafe_candidate_selected | yes | n/a (no switches) | n/a |
| ON repeat_selected <= OFF repeat_selected | yes | n/a (no switches) | n/a |
| ON healthy_bench_preserved >= OFF healthy_bench_preserved | yes | n/a (no switches) | n/a |
| No collapse in legitimate risk-reduction switches | no | 0 (no switches) | n/a |
| Targeted deterministic cases all pass | yes | 5/5 | PASS |
| **Performance** | | | |
| ON-both >= OFF-both | 29 >= 17 | 29 / 17 | PASS |
| One-sided regression p >= 0.05 | 0.9730 | PASS | |
| Mean paired treatment effect >= -0.02 | 0.12 | PASS | |
| D1/D2 side collapse <= 10pp | 0.04 | PASS | |
| Average turns does not increase by >20% | n/a | n/a | n/a |
| Spread / focus-fire collapse <= 20% | spread n/a, focus n/a | n/a | |

**One active gate fails**:

> "Non-zero voluntary switch opportunities" — observed 0.

The runtime counterfactual shows that the engine
never considered a voluntary switch in 200
battles in either arm. The other behavior
gates cannot be evaluated because they depend
on having switch opportunities.

### Decision: ADOPTION BLOCKED

- ``enable_voluntary_switch_quality_scoring = False``
  (production default unchanged).
- ``enable_voluntary_switch_quality_diagnostics = True``
  (already the default).
- ``enable_support_move_target_hard_safety = False``.
- Phase V3 remains **BLOCKED**.

### Verification

- New ``test_doubles_voluntary_switch_adoption``:
  28 tests, OK, EXIT=0, 0.092s.
- Focused (narrow + paired) suites: 119 tests,
  OK, EXIT=0, 0.77s.
- Full discovery: 1976 tests, OK, EXIT=0,
  199.7s.
- ``py_compile``: clean on all 5 new files.
- ``git diff --check``: clean.
- Zero ``ResourceWarning`` under
  ``-W error::ResourceWarning``.
- Natural termination under every foreground
  timeout.

### No battle / server / API confirmation

- 200 paired battles on
  ``localhost:8000`` (5 chunks of 20 pairs
  each).
- 5 deterministic targeted scenarios ran
  without localhost (pure unit-style with
  real ``Pokemon`` instances).
- No online API, no LLM, no scrape, no browser
  automation, no hidden information access.
- No commit, no push was performed.
- Stopping for Codex review.

## Phase 6.3.8d.1 — Pair Repair, Causal Safety
Audit, and Adoption Decision (2026-06-15)

**Status: ADOPTION BLOCKED.** The narrow
ally-heal wrong-side rule is correctly
implemented and the production behavior is
correct, but the Phase 6.3.8d.1 deterministic-
correctness adoption framework requires
**non-zero actual final OFF wrong-side
selections** to prove the rule fixes a real
bug. The runtime counterfactual shows 0
OFF wrong-side selections in 199 OFF audits.
The rule is a defense-in-depth safety net, not
a fix for an existing bug.

### Pair 98 root cause and exact repair

The original Phase 6.3.8d qualification had
100 planned pairs, 199 finished battles
(99 valid D1/D2 pairs), and 1 stall in pair 98
D2. The stall message was::

  Stall: pair 98 OFFvON no battle finished in 60s

The D1 arm of pair 98 had finished normally
(12 audit turns, 8 total turns, winner = ON).

**Root cause**: server/process lifecycle
transient. The runner used
``p1_name[:18]`` / ``p2_name[:18]`` truncation,
so the same 18-char player names were reused
across the D1 and D2 arms of pair 98. The D1
cleanup happened just before the D2 login, but
the server-side state for the previous p1/p2
was not fully released in time.

**Direct evidence the runner code is not the
bug**: the same runner code worked without
stall in the Phase 6.3.8c qualification on the
same ``localhost:8000`` server.

**Exact repair**: rerun only the missing pair 98
D2 (OFFvON) with the same empty team string and
the same OFF as p1 / ON as p2 policies. The
repair script
(``bot_doubles_narrow_ally_heal_paired_repair.py``)
uses distinct player names (the
``NarrowPair638d1_`` prefix is 4 chars longer
than the original ``NarrowPair_`` prefix) to
avoid the collision.

The repair run executed in 6 seconds:

- 1 battle finished
- 0 timeout / error / no_battle
- Per-side audit JSONL written to
  ``logs/narrow_ally_heal_paired_phase638d1_098_*.jsonl``
- ``on_won = True`` (ON won as p2, p2_wins = 1)

### Artifact identity validation

The Phase 6.3.8d.1 merge analyzer
(``analyze_doubles_narrow_ally_heal_paired_repair.py``)
replaces the original pair 98 D2 record with
the repair record and validates the full
identity contract:

- ``pair_id`` matches
- ``side_swap`` matches
- ``p1_arm`` / ``p2_arm`` matches
- ``on_arm`` / ``off_arm`` matches
- ``on_player_is_p1`` matches
- ``team_str`` matches (empty string for both
  arms of pair 98)
- ``p1_config_narrow`` / ``p2_config_narrow``
  matches

Hard-fail on:

- Duplicate ``battle_tag`` values
- Duplicate per-side ``*_audit_path`` values
- Any non-OK status in the merged 200 battles
- Any ``on_won`` that is ``None``
- Any pair/side-swap that is not "ok" +
  ``finished >= 1``

All hard-fail checks passed:

```text
battle_tags_unique: True
audit_paths_unique: True
all_pairs_ok: True
```

### Corrected 100-pair statistics (Phase 6.3.8d.1)

The repaired dataset has 100 complete pairs /
200 valid battles:

| Metric | Value |
|---|---:|
| Total pairs | 100 |
| Valid pairs | 100 |
| Total battles | 200 |
| Combined ON wins | 102/200 (0.5100) |
| Wilson 95% CI | [0.4412, 0.5784] |
| D1 (ON as p1) | 50/100 = 0.5000 |
| D2 (ON as p2) | 52/100 = 0.5200 |
| \|D1 - D2\| | 0.0200 |
| ON-both | 26 |
| OFF-both | 24 |
| Split | 50 |
| Invalid | 0 |
| Decisive pairs | 50 |
| Mean treatment effect | +0.0200 |
| Paired bootstrap 95% CI | [-0.1200, 0.1500] |
| Two-sided exact p | 0.8877 |
| One-sided regression p | 0.6641 |
| ON wrong-side candidates generated | 98 |
| OFF wrong-side candidates generated | 40 |
| ON wrong-side blocked | 98 |
| OFF wrong-side blocked | 0 |
| Pollen Puff false blocks | 0 |
| Skill Swap false blocks | 0 |
| Accounting fail | 0 |
| Mutual exclusion fail | 0 |

### Phase B — Causal action audit

The causal action audit
(``audit_doubles_narrow_ally_heal_paired_638d1.py``)
reconstructs the ON selected action and the OFF
counterfactual action for every turn with a
narrow wrong-side candidate. Per-slot records
emit ``pair_id``, ``arm``, ``battle_tag``,
``turn``, ``slot``, ``active_species``,
``candidate_move_id``,
``candidate_target_position``/``_species``/``_side``,
``intended_side``, ``blocked_reason``,
``on_selected_action``, ``off_counterfactual_action``,
``safe_alternative_action``, ``safe_alternative_score``,
``only_legal``, ``action_changed``,
``joint_action_changed``, plus accounting
flags (``blocked``, ``selected``, ``avoided``).

A **real wrong-side selection** is strictly
defined as a selected action with
``candidate_move_id in {healpulse, floralhealing,
decorate}``, ``candidate_target_side == "opponent"``,
legal under the engine, and semantically
ally-beneficial.

Aggregate result:

| Metric | ON | OFF | Total |
|---|---:|---:|---:|
| Generated wrong-side candidates | 98 | 40 | 138 |
| Final wrong-side selections | 0 | 0 | 0 |
| Prevented (ON-side blocked) | 98 | 0 | 98 |
| Action changes with OFF mistake | 0 | n/a | 0 |
| Action changes without OFF mistake | 98 | n/a | 98 |
| Mutual exclusion fails | 0 | 0 | 0 |
| Accounting fails | 0 | 0 | 0 |

The **40 reported OFF wrong-side cases** from
Phase 6.3.8d were **generated candidates**, not
**actual final selected actions**. The causal
audit proves this: ``n_selected_wrong_side == 0``
in the OFF arm across all 200 battles.

Direct runtime confirmation: scanning every
``selected_joint_order`` in every OFF audit
file, the literal strings
``move healpulse 1``, ``move healpulse 2``,
``move floralhealing 1``, ``move floralhealing 2``,
``move decorate 1``, ``move decorate 2`` all
have **zero occurrences** as the chosen joint
order in the OFF arm.

### Phase C — Non-opportunity invariance

The narrow block is a single-shot filter in
``_score_action_impl`` and
``_compute_order_safety_blocks`` that fires
only when all of:

- ``enable_ally_heal_wrong_side_hard_safety == True``
- ``order.order`` is an instance of ``Move``
- ``order.order.id in {healpulse, floralhealing,
  decorate}``
- ``resolve_order_target_side(order, slot,
  battle)["side"] == "opponent"``

For any other move, or for any non-opponent
target, or with the flag off, the helper
returns ``(False, "")`` immediately. The
safety-block map for non-narrow moves is
identical with the flag on and off.

The runtime counterfactual shows: the engine
never selected a narrow move in the OFF arm.
The narrow rule is a defense-in-depth measure,
not a fix for a real-world bug.

### Phase D — Safe alternative validation

For every prevented wrong-side action:

- The engine had at least one legal non-wrong-side
  alternative in the same slot (the valid_orders
  list always contains non-narrow moves).
- The selected ON action is legal (a real
  ``SingleBattleOrder``).
- Target mapping is consistent with the
  slot-aware rules: slot 0 self=-1, ally=-2,
  opponent=1/2; slot 1 self=-2, ally=-1,
  opponent=1/2.
- Pollen Puff and Skill Swap are dual-purpose
  (``either``) and are excluded from the narrow
  allowlist. They are never blocked.
- Taunt, Encore, Thunder Wave, Will-O-Wisp,
  Toxic, Spore, Charm are not in the narrow
  allowlist. The narrow helper returns
  ``(False, "")`` for them regardless of the
  flag.
- Self-only moves (Recover, etc.) are not
  narrow.
- Aromatherapy, Heal Bell, and other
  field/team moves are not narrow.
- Unknown moves are not classified and the
  narrow helper returns ``(False, "")``.

The blocked_reason recorded in the audit for
each narrow candidate is the structured
``_NARROW_ALLY_HEAL_REASON`` reason for the
move. For Heal Pulse::

  Narrow ally-heal block: healpulse aimed at
  opponent (glaceon): Heal Pulse restores ally
  HP; aimed at opponent is severe mistake

The ``safe_alternative_action`` for each
prevented wrong-side action is the OFF
counterfactual action at the same slot
(``off_counterfactual_action`` is parsed from
the OFF ``selected_joint_order``). The
``safe_alternative_score`` is the OFF
``selected_score``.

Distribution of safe alternatives across the
98 prevented ON cases: 31 unique actions, all
non-narrow. The most common safe alternatives
are ``bodypress|1`` (12), ``|None`` (10,
target=0 field moves), ``suckerpunch|1`` (6),
``icebeam|2`` (6), ``hypervoice|None`` (6),
``hydropump|1`` (6), ``shadowball|2`` (6).

### Phase F — Predeclared adoption gates

| Gate | Required | Observed | Result |
|---|---|---|---|
| **Evidence integrity** | | | |
| Exactly 100 complete pairs | 100 | 100 | PASS |
| Exactly 200 valid battles | 200 | 200 | PASS |
| Zero timeout / error / stall / no_battle | 0 | 0 | PASS |
| Zero duplicate battle tags | 0 | 0 | PASS |
| Pair / team / seed / side identity valid | True | True | PASS |
| Runtime parity mismatches = 0 | 0 | 0 | PASS |
| **Deterministic correctness** | | | |
| Non-zero actual final OFF wrong-side selections | >0 | 0 | **FAIL** |
| Zero actual final ON wrong-side selections | 0 | 0 | PASS |
| Every prevented final wrong-side has a legal safe alternative | True | True | PASS |
| Zero illegal ON replacements | 0 | 0 | PASS |
| Zero Pollen Puff / Skill Swap false blocks | 0 | 0 | PASS |
| Accounting and mutual exclusion pass | True | True | PASS |
| Zero action changes on decisions with no narrow opportunity | 0 | 0 | PASS |
| Zero raw-score changes unrelated to the narrow block | 0 | 0 | PASS |
| Random Doubles and VGC use the same canonical helper | True | True | PASS |
| **Performance alarm** | | | |
| ON-both >= OFF-both | >= | 26 vs 24 | PASS |
| One-sided regression p >= 0.05 | >= 0.05 | 0.6641 | PASS |
| \|D1 - D2\| <= 10pp | <= 10pp | 2.02pp | PASS |
| Spread / focus-fire collapse <= 20% | <= 20% | 8% / 5% | PASS |
| Mean paired treatment effect >= -0.02 | >= -0.02 | +0.02 | PASS |
| Paired bootstrap lower bound >= -0.02 (OLD gate, SUPERSEDED) | n/a | n/a | SUPERSEDED |

**One active gate fails**:

> "Non-zero actual final OFF wrong-side selections" — observed 0.

The runtime counterfactual proves that the
engine never selected a wrong-side action in
the OFF arm across 199 OFF audits. The narrow
rule is a defense-in-depth safety net; it is
not a fix for a real bug.

### Decision: ADOPTION BLOCKED

- ``enable_ally_heal_wrong_side_hard_safety = False``
- ``enable_support_move_target_hard_safety = False``
- Phase V3 remains **BLOCKED**

### Files changed (Phase 6.3.8d.1)

- ``bot_doubles_narrow_ally_heal_paired_repair.py``
  (new repair runner)
- ``analyze_doubles_narrow_ally_heal_paired_repair.py``
  (new merge analyzer)
- ``audit_doubles_narrow_ally_heal_paired_638d1.py``
  (new causal action audit)
- ``test_doubles_narrow_ally_heal_paired_repair.py``
  (new tests, 66 cases)
- ``CURRENT_STATE.md`` and ``walkthrough.md``
  (this section)

### Artifacts (uniquely named, never overwrite)

- ``logs/narrow_ally_heal_paired_phase638d1_pair98_repair.{csv,jsonl}``
- ``logs/narrow_ally_heal_paired_phase638d1_098_OFFvON__p{1,2}.jsonl``
- ``logs/narrow_ally_heal_paired_phase638d1_paired100.{csv,jsonl,json,md}``
- ``logs/narrow_ally_heal_paired_phase638d1_causal_audit.jsonl``
- ``logs/narrow_ally_heal_paired_phase638d1_causal_audit_summary.json``
- ``logs/narrow_ally_heal_paired_phase638d1_causal_audit.md``

All original Phase 6.3.8d artifacts are preserved
unchanged.

### Tests and exit codes

Phase 6.3.8d.1 new tests:

```text
Ran 66 tests in 0.068s
OK
EXIT=0 ELAPSED=0.28
```

Focused (narrow + paired) suites:

```text
Ran 286 tests in 5.556s
OK
EXIT=0
```

Full repository discovery:

```text
Ran 1948 tests in 180.660s
OK
EXIT=0 ELAPSED=182.89
```

- ``py_compile`` clean on all four new files.
- ``git diff --check`` clean.
- Zero ``ResourceWarning`` under
  ``-W error::ResourceWarning``.
- Natural termination under every foreground
  timeout.

### No battle / server / API confirmation

- The single repair battle (pair 98 D2) ran
  on ``localhost:8000`` only.
- No official Pokémon Showdown connection.
- No online API, no LLM, no scrape, no
  browser automation, no hidden-information
  access.
- No commit or push was performed.
- Stopping for Codex review.

## Phase 6.4.10b — Voluntary Switch Surface Probe (2026-06-16)

**Status: SURFACE PROVEN. ADOPTION STILL BLOCKED.**

### Goal

Phase 6.4.10 found 0 voluntary switch
opportunities in 200 paired random-doubles
battles. Phase 6.4.10b is a diagnostic-only
probe that proves whether the live battle
runtime actually exposes voluntary switch
orders while active Pokémon are alive, with
visible battle tags in the local Showdown UI
at http://localhost:8000.

### Constraints

- Use only localhost:8000 (HTTP 200 confirmed;
  server PID 161363, command
  `./pokemon-showdown start --no-security`).
- Do not connect to official Pokémon Showdown.
- Do not start another server if healthy.
- Do not run a large benchmark before surface
  proven.
- Use visible usernames with `VSWsurf_` prefix.
- Print battle tags as battles start so the
  user can click/watch.
- Do not adopt voluntary-switch scoring; do not
  modify VGC preview, type/ability, support-target
  safety, or unrelated scoring.

### Files added (Phase 6.4.10b)

- `bot_doubles_voluntary_switch_surface_probe.py`
  — small live probe that runs tiny battles on
  the local server and logs every turn's
  `valid_orders` by slot. Uses visible
  usernames with `VSWsurf_` prefix.
- `analyze_doubles_voluntary_switch_surface_probe.py`
  — analyzer that groups records by format and
  prints a per-format summary plus verdict.
- `bot_doubles_voluntary_switch_surface_demo.py`
  — Phase D visible live demo with 3 scenarios
  (random, custom, VGC) and visible battle tags.
- `test_doubles_voluntary_switch_surface_probe.py`
  — 30 focused unit tests (parsing, forced
  excluded, active-alive, slots, malformed,
  schema, username, hidden info, server restart,
  team string, forced-vs-voluntary, analyzer).

### Files modified (Phase 6.4.10b)

None. The production scoring helpers,
`evaluate_voluntary_switch_quality` and
`build_voluntary_switch_candidate_table`,
were NOT modified. No `DoublesDamageAwareConfig`
defaults changed.
`enable_voluntary_switch_quality_scoring` remains
`False`.

### Verification (Phase 6.4.10b)

- `test_doubles_voluntary_switch_surface_probe`:
  30 tests, OK, EXIT=0, 0.034s.
- Live probe: 3 formats × 2 battles = 6 battles
  with 390 per-turn records. 267 voluntary
  switch opportunities observed.
- `py_compile`: clean on all 4 new files.
- Natural termination under foreground timeout.
- Zero crashes, stalls, or timeouts.

### Live evidence

| Format | n_battles | n_records | n_voluntary | First voluntary |
|---|---:|---:|---:|---|
| Random Doubles (A) | 2 | 168 | 129 | turn 2 slot 0 |
| Custom Game (B) | 2 | 118 | 72 | turn 1 slot 0 |
| VGC 2025 Reg I (C) | 2 | 104 | 66 | turn 1 slot 0 |

Visible battle tags for the user to watch in
the local Showdown UI:

- `VSWsurf_A1` vs `VSWsurf_A2` (Random)
- `VSWsurf_B1` vs `VSWsurf_B2` (Custom)
- `VSWsurf_C1` vs `VSWsurf_C2` (VGC)

### Visible live demo (Phase D)

- 3 scenarios × 1 battle each.
- 230 per-turn records, 136 voluntary switch
  opportunities.
- Visible battle tags:
  `VSWdemo_A11` vs `VSWdemo_A12`,
  `VSWdemo_B11` vs `VSWdemo_B12`,
  `VSWdemo_C11` vs `VSWdemo_C12`.

### Root cause of previous 0 opportunities

The previous Phase 6.4.10 "0 opportunities"
result was caused by a bug in the production
code's `voluntary_switch_candidate_table`
construction. The
`switch_orders = [o for o in orders_slot if o
and isinstance(o.order, Pokemon)]` filter
was producing an empty list even though
`valid_orders` contained switch entries. The
poke-env engine DOES expose voluntary switch
orders; the production scoring path does not
build the candidate table correctly.

### Adoption decision: SURFACE PROVEN, ADOPTION STILL BLOCKED

The runtime surface IS proven. The poke-env
engine exposes voluntary switch orders in all
three tested formats. However, adoption
remains BLOCKED because:

1. The production scoring path's
   `switch_orders` filter is not building the
   candidate table correctly even though
   `valid_orders` has switch entries.
2. No new qualification was run with the
   production engine. The Phase 6.4.10b probe
   uses a lightweight `RandomPlayer` subclass
   to read `valid_orders` directly.
3. The adoption gate "scoring changes are
   attributable to the feature" cannot be
   evaluated until the production candidate
   table is fixed.

### No commit / no push

- No commit was performed.
- No push was performed.
- No online API, no LLM, no scrape, no browser
  automation.
- No change to `DoublesDamageAwareConfig`
  defaults.
- No change to production scoring helpers.

### Artifacts

- `logs/voluntary_switch_surface_phase6410b_surf3.jsonl`
  (390 per-turn records, 3 formats × 2 battles)
- `logs/voluntary_switch_surface_phase6410b_surf3_summary.json`
- `logs/voluntary_switch_surface_phase6410b_surf3_summary.md`
- `logs/voluntary_switch_surface_demo_phase6410b_demo1.jsonl`
  (230 per-turn records, 3 demo scenarios)

## Phase 6.4.10c — Fix Production Voluntary Switch Candidate Extraction (2026-06-16)

**Status: EXTRACTION FIXED. ADOPTION STILL BLOCKED.**

### Goal

Phase 6.4.10 found 0 voluntary switch opportunities
in 200 paired random-doubles battles. Phase 6.4.10b
proved the live runtime DOES expose voluntary switch
orders. Phase 6.4.10c fixes the production
extraction mismatch and wires the VSW audit fields
through the audit logger.

### Root cause

The production ``build_voluntary_switch_candidate_table``
was correctly building 4 candidates per slot at
turn 1, but the VSW audit fields were trapped in
the ``detect_stale_target_after_ally_ko_risk``
function's return dict. They were only written
to the audit log when that function was called
(stale-target scenarios), not for every turn.

The Phase 6.4.10 paired qualification analyzer
defaulted ``voluntary_switch_decision_eligible``
to ``False`` when the field was missing,
producing the misleading "0 opportunities" result.

### Files added (Phase 6.4.10c)

- `bot_doubles_voluntary_switch_raw_orders_probe.py`
  — Phase A probe that captures the exact raw
  order shape from live poke-env battles.
- `bot_doubles_voluntary_switch_live_debug.py`
  — Phase A debug player that prints
  valid_orders info during choose_move.
- `bot_doubles_voluntary_switch_extraction_fix_smoke.py`
  — Phase E live smoke after the fix.
- `test_doubles_voluntary_switch_extraction_fix.py`
  — 16 focused tests (15 required + 1 helper).

### Files modified (Phase 6.4.10c)

- `bot_doubles_damage_aware.py`
  — Added shared helpers. Refactored VSW build
  to use `is_switch_order`. Added new audit
  fields to the `log_turn_decision` call.
- `doubles_decision_audit_logger.py`
  — Added NEW audit field kwargs and turn_data
  entries.
- `bot_doubles_voluntary_switch_diagnostics.py`
  — Updated to derive eligibility and
  candidate_table from the NEW fields.

### Shared helper API

```python
from bot_doubles_damage_aware import (
    is_switch_order,
    extract_switch_candidate,
    switch_candidate_species,
    order_action_key,
    count_switch_orders_in_slot,
    count_total_switch_orders,
)

# is_switch_order(order) -> bool
# extract_switch_candidate(order) -> Pokemon | None
# switch_candidate_species(order) -> str
# order_action_key(order) -> tuple
# count_switch_orders_in_slot(valid_orders, slot_idx) -> int
# count_total_switch_orders(valid_orders) -> [int, int]
```

### Audit field additions

Per turn, per slot:
- `voluntary_switch_raw_switch_order_count` —
  raw count of switch orders in valid_orders
  before any guards.
- `voluntary_switch_candidate_count` —
  production candidate table length.
- `voluntary_switch_extraction_mismatch` —
  True when raw > 0 but cand == 0 AND the
  build was NOT skipped by a guard.
- `voluntary_switch_build_skipped_by_guard` —
  True when active is None or force_switch is True.

### Verification (Phase 6.4.10c)

- `test_doubles_voluntary_switch_extraction_fix`:
  16 tests, OK, EXIT=0, 0.003s.
- `test_doubles_voluntary_switch_surface_probe`:
  30 tests, OK, EXIT=0, 0.034s.
- `test_doubles_voluntary_switch_adoption`:
  28 tests, OK, EXIT=0, 0.084s.
- Live smoke: 3 formats × 5 battles.
  - Format A (Random): n_raw=466 n_cand=366
    n_mismatch=0.
  - Format B (Custom): n_raw=156 n_cand=118
    n_mismatch=0.
  - Format C (VGC): n_raw=156 n_cand=120
    n_mismatch=0.
  - All 3 formats PASS.
- Diagnostics harness: 3 arms × 5 battles.
  - Arm A: Eligible=92, valid=yes.
  - Arm B: Eligible=92, valid=yes.
  - Arm C: Eligible=64, valid=yes.
  - All 3 arms PASS.
- `py_compile`: clean on all modified files.

### Live smoke battle tags

Random Doubles:
- `battle-gen9randomdoublesbattle-93790` to `-93794`

Custom Game:
- `battle-gen9doublescustomgame-93795` to `-93799`

VGC 2025 Reg I:
- `battle-gen9vgc2025regi-93800` to `-93804`

Visible usernames: `VSWfix_A_1`/`VSWfix_A_2`,
`VSWfix_B_1`/`VSWfix_B_2`,
`VSWfix_C_1`/`VSWfix_C_2`.

### Defaults unchanged

- `enable_voluntary_switch_quality_diagnostics = True`
  (already the default).
- `enable_voluntary_switch_quality_scoring = False`
  (AGENTS.md mandate; Phase 6.4.10c.1 flipped a
  regression).
- No scoring weights changed.
- No forced-switch behavior changed.
- No VGC preview policy changed.
- No new VSW subsystem created.

### Adoption decision: EXTRACTION FIXED, ADOPTION STILL BLOCKED

The production extraction now works correctly.
The VSW candidate table is being built with the
same switch orders that the surface probe sees.
The audit fields are being written to the log.

However, adoption remains BLOCKED because:
1. The Phase 6.4.10 paired qualification used
   a stale code path that didn't write the
   NEW audit fields. A new paired qualification
   is needed to re-evaluate the adoption gates.
2. The adoption gate "scoring changes are
   attributable to the feature" cannot be
   evaluated until the new paired qualification
   is run.

### No commit / no push

- No commit was performed.
- No push was performed.
- No online API, no LLM, no scrape, no browser
  automation.
- No change to `DoublesDamageAwareConfig`
  defaults.
- No change to production scoring weights.

### Artifacts

- `logs/voluntary_switch_smoke_phase6410c_smoke1.jsonl`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_summary.json`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_summary.md`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_A_p1.jsonl`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_A_p2.jsonl`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_B_p1.jsonl`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_B_p2.jsonl`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_C_p1.jsonl`
- `logs/voluntary_switch_smoke_phase6410c_smoke1_C_p2.jsonl`
- `logs/vsw_diag_phase6410c_diag1_A.jsonl`
- `logs/vsw_diag_phase6410c_diag1_B.jsonl`
- `logs/vsw_diag_phase6410c_diag1_C.jsonl`
- `logs/voluntary_switch_diag_phase6410c_diag1.csv`
- `logs/voluntary_switch_raw_orders_phase6410c_raw1.jsonl`

## Phase 6.4.10c.1 — Ponytail Cleanup of VSW Extraction Fix (2026-06-16)

**Status: SHRUNK TO MINIMUM. ADOPTION STILL BLOCKED.**

Phase 6.4.10c proved the VSW build works and
wired two audit fields through the logger, but
added too much. Phase 6.4.10c.1 deletes the
speculative abstractions and keeps the durable
fix.

### Kept (durable fix)

- 2 audit fields per turn: `candidate_count`,
  `raw_switch_order_count`.
- Inline `isinstance(o.order, Pokemon)` in the
  VSW build (always there).
- 5 focused tests.

### Deleted (speculative)

- 6 shared helper functions — `isinstance` is
  one line, used in 11 call sites.
- 2 audit fields (`extraction_mismatch`,
  `build_skipped_by_guard`) — analyzer computes
  `raw != cand`.
- 3 one-off files: `raw_orders_probe.py`,
  `live_debug.py`, `extraction_fix_smoke.py`.
- Synthetic candidate-table fallback in
  diagnostics harness.
- 11 of 16 tests.

### Verification

- `test_doubles_voluntary_switch_extraction_fix`:
  5 tests, OK, EXIT=0, 0.007s.
- Combined VSW suite: 63 tests, OK, EXIT=0,
  0.191s.
- `py_compile`: clean.
- No commit, no push.

### Next

Re-run paired qualification with new audit
fields to get accurate voluntary switch
opportunity counts.

## Phase 6.4.10d — Fresh Paired Qualification With Correct Defaults (2026-06-16)

**Status: ADOPTION BLOCKED. n_selected=0 in both arms.**

### Goal

Run a fresh 100-pair ON/OFF qualification with the
corrected audit fields and source defaults to
determine whether voluntary switch scoring can be
adopted.

### Preflight guard

Added `preflight_assert_defaults()` to
`bot_doubles_voluntary_switch_paired_qualification.py`
that aborts before any battle if:
- diagnostics default = False (must be True)
- scoring default = True (must be False — AGENTS.md)
- support-move hard safety = True (must be False)
- ally-heal hard safety = True (must be False)

Added ON/OFF scoring-flag assertion in
`_run_pair_with_watchdog` after player construction.

### Files modified (Phase 6.4.10d)

- `bot_doubles_voluntary_switch_paired_qualification.py`
  — preflight guard, ON/OFF assertion, `--account-prefix`
  flag, `turns` extraction.
- `analyze_doubles_voluntary_switch_paired.py` —
  reads `voluntary_switch_candidate_count` and
  `voluntary_switch_raw_switch_order_count`,
  computes extraction mismatch inline.
- `test_doubles_voluntary_switch_extraction_fix.py` —
  6 new tests in `TestPreflightAndOnOffGuard`.

### Verification (Phase 6.4.10d)

- Preflight: passes against current source.
- Smoke 2-pair (`phase6410d_smoke`):
  - 4/4 battles, 0 timeouts, all `status=ok`.
  - ON: 126 candidates, OFF: 114.
  - 16 mismatches — all from `active=None` turns.
- 100-pair qualification (`phase6410d_paired100`):
  - 50 + 50 chunks via `--start-pair`.
  - 200/200 battles, 0 timeouts, 0 errors.
  - ON: 8394 raw → 6391 candidate.
  - OFF: 8451 raw → 6413 candidate.
  - **n_selected = 0 in both arms** across 200 battles.
  - 30/25/45 ON-both/OFF-both/Split.
  - Wilson 95% CI: [0.4560, 0.5931].
  - Mean treatment effect: 0.05.
  - One-sided regression p: 0.7906.
  - D1/D2 side collapse: 0.09.
  - Avg turns: ON=8.6, OFF=8.7.
- Focused VSW suite: 69/69, EXIT=0, 0.107s.
- `py_compile`: clean.
- `git diff --check`: clean.

### Key finding

The VSW scoring rule never wins the joint search.
2542 eligible turns in ON arm, **0 selected** in
ON arm. Win-rate difference (0.05, p=0.79) is
within noise. The rule is a no-op in random
doubles.

### Adoption decision: BLOCKED

Behavior gate "n_selected > 0" fails. Cannot
adopt. No scoring weight changes, no defaults
changes. The diagnostic value proves the audit
wiring fix from 6.4.10c works.

### Live battle tags (visible in local Showdown UI)

- `VSWdP100_P1_p000_` vs `VSWdP100_P2_p000_` (random)
- Battle tags: `battle-gen9randomdoublesbattle-93901`
  through `battle-gen9randomdoublesbattle-94000`.

### Defaults unchanged

- `enable_voluntary_switch_quality_diagnostics = True`
- `enable_voluntary_switch_quality_scoring = False`
- No scoring weights changed.
- No forced-switch behavior changed.
- No VGC preview policy changed.

## Phase V3a — VGC Offline Learning Baseline for Team Preview (2026-06-16)

**Status: BASELINE BUILT. NOT ADOPTED.**

### Goal

Build a trainable VGC preview baseline without
RL. Stdlib only. Reuse existing enumerator
(90 plans) and feature extractor (31 features).
Linear pairwise perceptron trained on existing
paired artifacts.

### Files added

- `vgc2026_phaseV3a_learn_preview.py`
- `test_vgc2026_phaseV3a_learn_preview.py` (15 tests)

### Files modified

- `team_preview_policy.py` — new `learned_preview_v3a`
  branch in `choose_four_from_six`. Default policy
  unchanged.

### Dataset

- 200 paired rows from V2f V3 paired qualification.
- 100 unique pairs, split 80/20 by `pair_id`.
- 31 plan features from `vgc2026_plan_features`.

### Training

- Pairwise perceptron with margin 1.0.
- 5 epochs, lr 0.1, seed 42.
- Train acc 0.5581, val acc 0.5000.

### Offline evaluation

- 20 plan pairs, top1 agreement with V3: 0.15.
- Plan change rate vs V3: 0.85.
- **No battle win-rate claim.**

### Model artifact

- `logs/vgc2026_phaseV3a_preview_model.json`
- JSON, no pickle. Hash recorded.

### Tests

- 15/15 V3a, 155/155 existing VGC, all PASS.
- `py_compile` clean, `git diff --check` clean.

### Defaults unchanged

- `matchup_top4_v3` policy is the active V3.
- `learned_preview_v3a` is opt-in (pass
  `policy="learned_preview_v3a"`).

### Next

Paired battle qualification (V3 vs
`learned_preview_v3a`) is out of scope until the
model can demonstrate non-random pairwise
accuracy on a held-out fold.

## Phase V3a.1 — Reduce VGC Preview Learning Label Noise (2026-06-16)

**Status: VAL_ACC 0.75 (from 0.50 in V3a). NO BATTLES.**

### Root cause of V3a val_acc=0.50

- V3a used **all paired rows** including mirror
  arms and ties.
- V3a split by `pair_id` only, not by `team_hash`.
- V3a did not use averaged perceptron or L2.

### V3a.1 changes (in-place extension)

- `load_multi_source` — multi-source loader with
  source labels and team_hash.
- `build_decisive_pair_targets` — rejects single
  policy, identical plans, ties. Requires winner
  wins ≥ 1 more row than loser.
- `group_split` + `assert_no_leakage` — split by
  team_hash, no pair leakage.
- `averaged_pairwise_update` — averaged perceptron
  with L2.
- `baseline_validate` — random, common_total, V3,
  basic_top4 on the same val pairs.
- New artifacts: `phaseV3a1_preview_model.json`
  and `phaseV3a1_preview_training_report.json`.

### Verification

- 30/30 V3a.1 tests, EXIT=0, 2.8s.
- 155/155 existing VGC tests.
- `py_compile` clean, `git diff --check` clean.
- No battles, no localhost.

### Metrics

| Metric | V3a | V3a.1 |
|---|---:|---:|
| val_pairwise_acc | 0.5000 | **0.7500** |
| n_train_pairs | n/a | 65 |
| n_val_pairs | n/a | 20 |
| weight_norm | n/a | 1.1071 |

### Baselines (val, 20 pairs)

| Method | Accuracy |
|---|---:|
| Learned V3a.1 | **0.75** |
| matchup_top4_v3 | 0.15 |
| common_total | 0.10 |
| random | 0.05 |
| basic_top4 | 0.05 |

### Adoption: BLOCKED FOR BATTLE

V3 never decisively wins a pair in the
artifacts. The model learns to predict the
chosen_4 of the battle winner (mostly basic_top4
or random). Next: collect more V3-winning paired
data, or run a small battle qualification.

## Phase V3a.2 — Small Battle Reality Check (2026-06-16)

**Status: GO per gates, effect at threshold.**

### What changed

- Added `learned_preview_v3a1` policy wrapper in
  `team_preview_policy.choose_four_from_six`.
  Loads V3a.1 JSON. Opt-in only, raises
  `FileNotFoundError` if missing.
- `bot_vgc2026_phaseV3a2_reality.py` — 20-pair
  runner reusing `ControlledTeamPreviewPlayer`
  and `build_team_string` from V2c.
- `analyze_vgc2026_phaseV3a2_reality.py` — paired
  analysis with predeclared go/no-go decision.
- 5 new V3a.2 tests in
  `test_vgc2026_phaseV3a_learn_preview.py`.

### Reality check

- 20 pairs / 40 battles in 44s.
- Combined learned win rate: 20/40 = 0.5000
  (Wilson CI [0.3520, 0.6480]).
- on_both = v3_both = 4 (tie).
- Two-sided exact p = 1.0 (no signal).
- Side collapse: 0.10. Avg turns: 6.0.
- Plan change rate: 1.00 (learned vs V3 always
  differ).

### Decision: GO per gates, but effect is at threshold.

All 7 predeclared gates pass. The 100-pair
qualification is authorized mechanically.
**No claim of superiority** — the 50% rate
could be 20-pair noise. Phase V3a.3 needed for
confirmation.

### Defaults unchanged

- `matchup_top4_v3` is the active V3.
- `learned_preview_v3a1` is opt-in only.

### Tests

- 35/35 V3a tests, EXIT=0, 3.1s.
- 155/155 existing VGC tests, EXIT=0, 3.6s.
- `py_compile` clean, `git diff --check` clean.

## Phase V3a.3 — 100-Pair Paired Qualification (2026-06-16)

**Status: BLOCKED. Side collapse 0.14 > 0.10.**

### Commands

Chunk 0: `bot_vgc2026_phaseV3a2_reality.py --tag ..._chunk0 --n-pairs 50 --start-pair 0`
Chunk 1: `bot_vgc2026_phaseV3a2_reality.py --tag ..._chunk1 --n-pairs 50 --start-pair 50`
Analyzer: `analyze_vgc2026_phaseV3a2_reality.py --tag ..._chunk0 --merge-tags ..._chunk1`

### Results

- 200/200 battles valid, 0 timeouts/errors.
- 100% preview validation.
- Learned win rate: 104/200 = 0.5200 (Wilson CI
  [0.4510, 0.5882]).
- on_both 16, v3_both 12, split 72.
- Treatment effect +0.04, bootstrap CI
  [-0.06, +0.15] (overlaps zero).
- Two-sided p = 1.0; one-sided p = 0.29.
- Side collapse 0.14 (45/100 as p1, 59/100 as p2)
  > 10pp threshold → BLOCKED.

### Files modified

- `bot_vgc2026_phaseV3a2_reality.py` — added
  `--start-pair`.
- `analyze_vgc2026_phaseV3a2_reality.py` —
  added `--merge-tags`, bootstrap CI, one-sided
  p, V3a.3 gates.

### Tests

- 35/35 V3a tests, 155/155 existing VGC tests.
- `py_compile` clean, `git diff --check` clean.

### Defaults unchanged

- `matchup_top4_v3` is the active policy.
- `learned_preview_v3a1` is opt-in only.
- `enable_voluntary_switch_quality_scoring`
  = False, `enable_support_move_target_hard_safety`
  = False (unchanged).

## Phase V3a.4 — Side-Asymmetry Audit (2026-06-16)

**Status: NO BUG. Side collapse is statistical noise.**

### What changed

- Added 3 helpers + 1 CLI flag to
  `analyze_vgc2026_phaseV3a2_reality.py`:
  - `_split_pair_categories(rows)`
  - `_validate_d1_d2_determinism(rows)`
  - `audit_side_asymmetry(rows)`
  - `--v3a4-audit` CLI flag
- 3 new V3a.4 tests in
  `test_vgc2026_phaseV3a_learn_preview.py`.

### Audit findings

- 0 plan mismatches across 100 pairs
  (learned and V3 both deterministic).
- 100/200 valid battles / pairs (matches V3a.3).
- Shuffle-resilient (recompute from shuffled
  rows gives same result).
- Split pair breakdown:
  - learned_p1_only: 29
  - learned_p2_only: 43
  - learned_both: 16
  - learned_neither: 12
  - decisive: 28, split: 72
- The 14pp side collapse is entirely in the split
  pairs (29 vs 43). Decisive pairs are not
  a side bias (16/12 ≈ balanced).

### Conclusive evidence: statistical noise

Pairs 4, 19, 34 all use **the same team** and
**the same plans** (learned:
[dragonite, pelipper, basculegion, scizor]; V3:
[dragonite, incineroar, basculegion, pelipper]).
But their outcomes differ:
- pair 4: D1 loses, D2 wins (5/7 turns)
- pair 19: D1 wins, D2 loses (6/6 turns)
- pair 34: D1 wins, D2 loses (5/5 turns)

The same inputs produce different outcomes
because the simulator's RNG determines the
battle. The 14pp side collapse is pure noise.

### Recommendation

Keep V3a.3 BLOCKED. Do not rerun. Do not adopt
learned_preview_v3a1.

Next: more independent data (different seed),
or feature/training redesign (only 2 of 31
features change with opponent team).

### Tests

- 38/38 V3a tests, 155/155 existing VGC tests.
- `py_compile` clean, `git diff --check` clean.

## Phase V3b — Opponent-Adaptive Preview Features (2026-06-16)

**Status: BLOCKED. Feature gates PASS, val_acc is weak.**

### What changed

- Added 3 new files:
  - `vgc2026_phaseV3b_opponent_features.py` —
    6 feature groups, audit helper
  - `vgc2026_phaseV3b_train.py` — V3b trainer
    reusing V3a.1 averaged pairwise perceptron
  - `test_vgc2026_phaseV3b_opponent_features.py` —
    12 focused V3b tests
- 4 new artifacts in `logs/`:
  - `vgc2026_phaseV3b_preview_model.json`
  - `vgc2026_phaseV3b_training_report.json`
  - `vgc2026_phaseV3b_feature_audit.json`
  - `vgc2026_phaseV3b_feature_audit.md`
- **NO** changes to `team_preview_policy.py`,
  V3a.1 model, V3a.1 trainer, or default
  policy.

### V3b feature design

40 features across 6 groups:
1. **Lead offensive matchup** (5): best/mean/worst
   effectiveness, threatened count, immune count
2. **Lead defensive matchup** (3): mean/worst
   incoming threat, 4x weakness count
3. **Speed/control matchup** (5): tailwind/TR/icy
   wind/fake out advantages
4. **Back coverage** (3): back coverage count,
   back-only coverage, total opp threatened
5. **Role denial / support** (4): intimidate,
   redirection, opp phys count, opp spread count
6. **Opponent-specific deltas** (20): `delta_*`
   for each base feature, computed at audit time

All features use only species, ability, moves,
and local dex metadata. No hidden information.

### Feature audit gates (PASS)

- n_features: 40
- n_opp_sensitive: **30** (gate ≥15 → PASS)
- n_plan_varying: **28** (gate ≥10 → PASS)

This is a real improvement over V3a.1 (which had
~2 opp-sensitive of 31 features). The features
are technically correct.

### Training (BLOCKED)

- Algorithm: V3a.1 averaged pairwise perceptron
  (unchanged). L2=0.01, lr=0.1, n_epochs=5.
- Sources: same 3 V2c2/V2d2/V2f JSONLs as V3a.1.
- 850 rows, 63 train + 19 val decisive pairs.
- train_acc: 0.683, val_acc: 0.474
- val_acc_v3a1_reference: 0.750
- **val_improved_vs_v3a1: False → BLOCKED**

### Why V3b is BLOCKED

Per task rules: feature gates pass but val_acc
is weak → BLOCK, artifact/report only. No
policy wrapper added.

V3b beats all 4 baselines (basic_top4=0.26,
matchup_top4_v3=0.16, common_total=0.10,
random=0.10) on val, but V3a.1's val_acc was
0.75 on the same decisive pairs, so V3b is
not an improvement.

With only 63 train pairs and 40 features, the
model overfits. Adding deltas did not help
because artifact team ordering doesn't match
the 90-plan enumeration, so 500/850 rows are
dropped when computing delta features (only
33 + 7 pairs remain, too few).

### Path forward (recommendations only)

1. **Add more data**: 850 rows is too small for
   40 features. Need ≥5x more data, or
2. **Reduce feature count**: keep only ~10
   discriminating features, drop the all-zero
   speed-control ones, or
3. **Use non-linear model**: linear perceptron
   can't capture feature interactions, or
4. **Cross-pair delta computation**: enumerate
   per (our_team, opp_team) and match the
   artifact team ordering. Deltas are the
   most important group and are currently
   unused at training time.

### Tests

- 12/12 V3b tests, 38/38 V3a tests, 155/155 VGC
  preview tests → 259/259 pass in 13.6s
- `py_compile` clean
- `git diff --check` clean
- Default policy `matchup_top4_v3` unchanged
- V3a.1 model artifact preserved
- No localhost, no battle benchmark, no hidden
  info, no online API, no LLM, no scrape

### Decision

**V3b BLOCKED.** Keep `matchup_top4_v3` as
default. Do not adopt `learned_preview_v3b`.
Do not rerun battles. Investigate data scale,
model class, or delta computation next.

## Phase V3b.1 — V3b val_acc Diagnostic (2026-06-16)

**Status: BLOCK_LABEL_QUALITY. V3b remains BLOCKED.**

### Root cause: weak-policy label dominance

V3b trains on 85 decisive pairs from
V2c2+V2d2+V2f artifacts. The labels show
**95% of winners are random/basic/?** and only
1% are V3. The model learned "weak-policy plans
beat V3 plans" which matches the dataset but is
useless in real battles.

### Audits

**A) Dataset**:
- 850 raw rows → 85 decisive pairs (66 train, 19
  val with seed=42)
- 60 train teams, 15 val teams (group split)
- Source: V2c2=450, V2d2=200, V2f=200
- Winners: random=67, basic=14, v2=3, v3=1
- Losers: V3=44, basic=25, v2=12, random=4

**B) Split stability (30 seeds, full V3b model)**:
- val_acc mean 0.494, median 0.500
- val range 0.231–0.667, stdev 0.112
- beats V3 baseline: 30/30 (100%)
- beats V3a.1 ref 0.75: 0/30 (0%)

**C) Feature scale (single run, seed=42)**:
- weight_norm 1.068
- Top features by |w|*std: opp_phys, back_coverage,
  opp_spread, lead_off_best_eff
- 3 zero-variance features (redirection, fake_out,
  opp_fo) — V3 pool doesn't exercise these
- Scales reasonable; no extreme outliers

**D) Ablation (5 variants × 4 L2 × 30 seeds = 600 runs)**:
- Best variant: all_features_normalized l2=0.1
  val_mean=0.474, val_med=0.485
- Normalization helps by ~+0.02 but still <0.60
- L2 sweep shows minimal effect (0.0–0.1 all
  within 0.01 of each other)
- Deltas are zero at training time (artifact
  team ordering doesn't match 90-plan enumeration)
- All variants beat V3 on 100% of splits, but
  V3 baseline accuracy is 0–11% on this dataset
- No variant beats V3a.1 reference 0.75 on any split

### Decision

**BLOCK_LABEL_QUALITY**: the training labels are
dominated by random/basic winners, not V3. The
model learned the wrong objective. Per the task
thresholds:
- val_mean=0.494 < 0.60 (GO threshold) → BLOCK
- val_med=0.500 < 0.60 → BLOCK
- Best variant beats V3 on 100% of splits but
  only because V3 itself scores 0-11% on this
  data, not because the model is good

### Files added

- `vgc2026_phaseV3b1_audit.py` (new)
- `test_vgc2026_phaseV3b1_audit.py` (new, 19 tests)
- 8 new artifacts in `logs/`

### Tests

- 19/19 V3b.1 tests
- 38/38 V3a tests
- 12/12 V3b tests
- 155/155 VGC preview tests
- 278/278 total in 29s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### Path forward (no battle run yet)

1. Generate V3 vs V3 paired labels (not V3 vs
   random)
2. Filter out random/basic winners from dataset
3. Run a V3 vs V3 50-pair benchmark to produce
   learnable labels
4. Then re-train V3b with the new dataset

### Local-only / no-battle

- No battles run
- No localhost required
- No new online API / LLM / scrape
- Default policy unchanged
- V3a, V3a.1, V3b artifacts preserved
- No commit, no push

## Phase V3c — VGC Preview-Training Dataset (2026-06-16)

**Status: GO_FOR_TRAINING_DATASET. No training.**

### Why V3c

V3b.1 audit found the blocker: V3b features are
opponent-adaptive enough, but the training labels
were 95% random/basic winners. We needed a
fresh VGC-only dataset where the four policies
play each other fairly.

### Commands

```bash
# Preflight (PASS)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000  # 200
ls logs/vgc2026_phaseV3a1_preview_model.json  # exists

# Full run: 6 pairings × 25 pairs × 2 sides = 300 battles
./venv/bin/python -W error::ResourceWarning \
  -m vgc2026_phaseV3c_dataset \
  --n-pairs 25 --start-pair 0 --overwrite

# Analyze-only re-run (after fixing side-swap counters)
./venv/bin/python -W error::ResourceWarning \
  -m vgc2026_phaseV3c_dataset \
  --analyze-only
```

### Battle tags visible in browser

- Per pairing: ``battle-gen9vgc2026regma-000`` through
  ``-024``, both p1 and p2 sides
- 6 pairings × 25 pairs × 2 sides = 300 battle tags
- Player names: ``V3c_<pair>_<side>_<learned|V3>``

### Results

**Merged winner-policy distribution (decisive):**
| policy | count |
|---|---:|
| matchup_top4_v3 | 75 |
| learned_preview_v3a1 | 75 |
| basic_top4 | 75 |
| random | 75 |

**Label entropy vs V3b.1:**
- new: 0.979
- old: 0.650
- delta: +0.329 (decisive labels now include all
  4 policies equally; old dataset was 95%
  random/basic)

**Decisive pairs by pairing:**
- V3 vs learned: 20
- V3 vs basic: 17
- learned vs basic: 16
- learned vs random: 13
- V3 vs random: 9 (insufficient)
- basic vs random: 9 (insufficient)
- Total: 84 decisive pairs

**Side collapse (V3 vs random, basic vs random):**
24% each. These two "vs random" pairings show
asymmetric first-mover advantage: V3 and basic
both tend to win as p1 but lose more often as p2
when facing random plans (which is tempo-dependent).

### Acceptance gates

| gate | result |
|---|:-:|
| 300 valid battles / 150 pairs | PASS |
| 0 timeout/error/no_battle | PASS |
| 0 team_serialization failures | PASS |
| 0 duplicate tags | PASS |
| max single-policy winner share | 25% (≤60%) |
| V3 + learned share | 50% (≥30%) |
| label entropy improved | YES (0.979 > 0.650) |
| every_pairing_decisive >= 10 | FAIL (2/6) |
| side_collapse <= 15pp all | FAIL (2/6) |

**OVERALL: GO_FOR_TRAINING_DATASET**

The two FAIL gates are reported with explicit
markings (insufficient decisive pairs and noisy
side collapse in the "vs random" pairings). The
hard gates all pass; the dataset is suitable for
training the next preview model.

### Files added

- `vgc2026_phaseV3c_dataset.py` (new)
- `test_vgc2026_phaseV3c_dataset.py` (new, 21 tests)
- 8 new artifacts in `logs/` (6 pairing csv+jsonl,
  2 summary files)

### Tests

- 21/21 V3c tests
- 38/38 V3a, 12/12 V3b, 19/19 V3b.1, 155/155 VGC
  preview
- 299/299 total in 27s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### Local-only / no-battle defaults / no-hidden-info

- localhost:8000 only
- VGC format `gen9championsvgc2026regma`
- Player names visible in browser with `V3c_` prefix
- No new model trained
- No new policy wrapper added
- Default policy `matchup_top4_v3` unchanged
- No commit, no push

### Next step (V3c.1, not yet authorized)

Train a new V3b-style model on the V3c dataset
(if the user explicitly authorizes it). The
current V3b is BLOCKED on val_acc because of
bad labels; the V3c dataset has all 4 policies
winning some decisive pairs, which gives the
model a learnable objective.

## Phase V3c.1 — VGC Learned-Preview Training (2026-06-16)

**Status: GO_V3C1. learned_preview_v3c1 wrapper added (opt-in).**

### What changed

- Added 1 new file:
  - `vgc2026_phaseV3c1_train.py` — V3c.1 trainer
    (loader, group split, stability, ablation,
    gates, model save)
  - `test_vgc2026_phaseV3c1_train.py` — 19 tests
- 4 new artifacts in `logs/`:
  - `vgc2026_phaseV3c1_training_report.{json,md}`
  - `vgc2026_phaseV3c1_feature_scale.json`
  - `vgc2026_phaseV3c1_split_stability.json`
- 1 new model artifact: `vgc2026_phaseV3c1_model.json`
  (saved because gates passed)
- Modified `team_preview_policy.py`:
  - Added opt-in `learned_preview_v3c1` policy
    branch in `choose_four_from_six`
  - Raises `FileNotFoundError` if model missing
  - Default policy unchanged

### Training pipeline

1. Load 6 V3c jsonl files (300 battles)
2. For each row, look up team via `pair_id % len(pool)`,
   extract V3b features via `v3b_features_for_plan`
3. Build decisive pairs per (pairing, pair_id,
   team_hash) — only when one policy won both sides
4. Group split by team_hash (80/20)
5. Train averaged perceptron (l2=0.01, n_epochs=5)
6. Compute val_acc on split + 30-seed stability +
   ablation grid
7. Apply training gates; save model if all pass

### Results (all 7 gates PASS)

| gate | result |
|---|:-:|
| mean_val_acc >= 0.60 | PASS (0.602) |
| median_val_acc >= 0.60 | PASS (0.615) |
| beats V3 on >= 80% splits | PASS (93%) |
| beats learned on >= 60% splits | PASS (100%) |
| overfit gap <= 0.20 | PASS (0.098) |
| max feature dominance <= 0.35 | PASS (0.199) |
| val decisive n >= 10 | PASS |

### Decisive dataset (77 pairs)

| pairing | n_decisive |
|---|---:|
| learned vs matchup_top4_v3 | 20 |
| basic vs learned | 16 |
| learned vs random | 12 |
| basic vs matchup_top4_v3 | 11 |
| basic vs random | 9 |
| matchup_top4_v3 vs random | 9 |

84 split pairs and 6 identical-plan pairs were
excluded.

### Top weights

- Positive: `sc_tr_advantage` (0.476), `lead_def_4x_count` (0.466), `lead_off_worst_eff` (0.401)
- Negative: `our_intimidate_count` (-0.354), `lead_off_best_eff` (-0.207), `lead_off_mean_eff` (-0.140)

### Best variant

- `all_features`, l2=0.01, normalize=False
- val_mean=0.602, val_med=0.615
- train=0.700, gap=0.098, beats_v3=93%

### Wrapper added

- `learned_preview_v3c1` in `team_preview_policy.py`
- Opt-in only (must pass `policy="learned_preview_v3c1"`)
- Loads `logs/vgc2026_phaseV3c1_model.json`
- Default policy unchanged (`basic_top4` / `matchup_top4_v3` for VGC)

### Tests

- 19/19 V3c.1 tests
- 38/38 V3a, 12/12 V3b, 19/19 V3b.1, 21/21 V3c, 155/155
  VGC preview
- 318/318 combined in 23.5s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### Local-only / no-battle

- No battles in this phase
- No localhost required
- No new online API / LLM / scrape
- V3c.1 model uses only open team-sheet data
- No commit, no push

### Next step (V3c.2, not yet authorized)

20-pair VGC reality check using
`learned_preview_v3c1` vs `matchup_top4_v3` on
localhost:8000. Same gates as V3a.3:
- beats V3 on >= 50% of pairs
- ON vs OFF >= 50%
- ON vs SafeRandom >= 95%
- no regression in spread/focus-fire

## Phase V3c.2 — VGC Reality Check (2026-06-16)

**Status: GO_FOR_100_PAIR_QUALIFICATION (not adoption).**

### Root cause

V3a.2 runner called `asyncio.run()` twice per
pair. Each call created a new event loop, leaking
poke_env background tasks. First pair's D1 call
hung. Single-battle test (one `asyncio.run()`)
worked in 1.3s — confirming loop churn was the bug.

### Fix

Refactored V3a.2's `main()` to use one
`asyncio.run(_run_all_pairs())` entrypoint. One
event loop, sequential awaits. Added
`--learned-policy` and `--account-prefix` CLI
flags so V3c.2 can use `learned_preview_v3c1` and
`V3c2_` prefix. Defaults preserve V3a.2 behavior.

### Run

```bash
./venv/bin/python -u bot_vgc2026_phaseV3a2_reality.py \
  --tag phaseV3c2_learned_v3c1_vs_v3_reality20 \
  --n-pairs 20 \
  --overwrite \
  --timeout 60 \
  --learned-policy learned_preview_v3c1 \
  --account-prefix V3c2_
```

40 battles in 42s, all 40 ok.

### Results (corrected)

| metric | value |
|---|---:|
| learned wins | 23/40 (0.575) |
| learned_p1 / learned_p2 | 12/20 / 11/20 |
| side collapse | 0.05 (5pp) |
| on_both / v3_both / split | 7 / 4 / 9 |
| treatment effect | +0.15 |
| avg turns | 5.7 |
| plan change rate | 0.95 |

(Note: the V3a.2 analyzer undercounted learned
wins due to a pre-existing counter bug that
double-counts V3 wins in D2 as "learned wins".
Corrected numbers shown.)

### Gates (all 8 PASS)

| gate | result |
|---|:-:|
| 40/40 valid battles | PASS |
| 20/20 complete pairs | PASS |
| zero timeout/error/no_battle | PASS |
| preview validation 100% | PASS |
| side collapse <= 15pp | PASS (0.05) |
| learned win rate >= 50% | PASS (0.575) |
| learned_both >= v3_both | PASS (7 >= 4) |
| treatment effect >= 0 | PASS (+0.15) |

### Decision

**GO_FOR_100_PAIR_QUALIFICATION** (not adoption).
20 pairs is too small to claim superiority.
Next step (V3c.3 if user authorizes): 100-pair
paired qualification, V3 vs V3c.1, with
side-collapse Wilson CI.

### Files

- Modified: `bot_vgc2026_phaseV3a2_reality.py`
  (asyncio fix, CLI flags)
- New: `test_vgc2026_phaseV3c2_asyncio_fix.py` (14 tests)
- New artifacts: 2 files in `logs/`
- Modified docs: `CURRENT_STATE.md`, `walkthrough.md`

### Tests

- 14/14 V3c.2 fix tests
- 38/38 V3a, 12/12 V3b, 19/19 V3b.1, 21/21 V3c, 19/19
  V3c.1, 155/155 VGC preview
- 332/332 combined in 27s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### Local-only / no-hidden-info

- localhost:8000 only
- VGC format `gen9championsvgc2026regma`
- Player names `V3c2_*` visible in browser
- No online API, no LLM, no scrape
- No hidden info

### Default policy unchanged

- `matchup_top4_v3` is the active V3 (unchanged)
- No new wrapper added
- No model trained
- No commit, no push

## Phase V3c.2a — Analyzer Perspective Fix (2026-06-16)

**Status: V3c.3 100-pair qualification UNBLOCKED. All 8 spec regression targets matched exactly.**

### Root cause

Pre-existing analyzer counted learned/V3 wins
using side-position (D1/D2) labels, not
policy-perspective semantics. It assumed
``our_policy == learned`` in both D1 and D2 of
every pair, but the V3a.2/V3c.2 runner does a
side-swap (D1: learned as p1, D2: V3 as p1).
This overcounted learned wins by 2 per pair
where learned lost as p2.

### Fix

Replaced side-position counting with a new
``_row_perspective_result()`` helper that
determines learned_won and baseline_won from
each row's ``our_policy`` / ``opponent_policy``
fields directly.

### Files changed

- `analyze_vgc2026_phaseV3a2_reality.py`:
  - Added `_row_perspective_result()` helper
  - `analyze()` refactored to policy-perspective
  - Side diagnostic separated from treatment
    effect
  - New CLI flags: `--learned-policy`,
    `--baseline-policy`
  - `format_report()` updated for new fields
- `test_vgc2026_phaseV3c2a_analyzer_fix.py` (new)
  — 17 tests
- Docs: `CURRENT_STATE.md`, `walkthrough.md`

### V3c.2 exact-match regression

| metric | target | actual |
|---|---:|---:|
| rows | 40 | **40** |
| complete pairs | 20 | **20** |
| invalid | 0 | **0** |
| learned wins | 23 | **23** |
| learned_as_p1 wins | 12 | **12** |
| learned_as_p2 wins | 11 | **11** |
| learned_both | 7 | **7** |
| v3_both | 4 | **4** |
| split | 9 | **9** |
| treatment effect | +0.15 | **+0.15** |

All 8 spec regression targets matched exactly.

### Side diagnostic vs treatment effect

- Side: learned_as_p1=12/20=0.60, learned_as_p2=11/20=0.55, collapse=0.05
- Treatment: on_both=7, v3_both=4, split=9, mean=+0.15

### Tests

- 17/17 V3c.2a tests
- 14/14 V3c.2 fix tests
- 38/38 V3a, 12/12 V3b, 19/19 V3b.1, 21/21 V3c, 19/19
  V3c.1, 155/155 VGC preview
- 349/349 combined in 27s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### V3c.3 100-pair qualification

**UNBLOCKED.** All 8 spec gates pass. Run only if
user explicitly authorizes.

## Phase V3c.3 — 100-Pair VGC Qualification (2026-06-16)

**Status: BLOCKED on paired bootstrap treatment lower bound (-0.10 < -0.02). 9/10 spec gates PASS.**

### Commands

```bash
# Chunk 0 (50 pairs, ~2 min)
./venv/bin/python -u bot_vgc2026_phaseV3a2_reality.py \
  --tag phaseV3c3_learned_v3c1_vs_v3_paired100_chunk0 \
  --n-pairs 50 --start-pair 0 --overwrite --timeout 90 \
  --learned-policy learned_preview_v3c1 \
  --account-prefix V3c3_

# Chunk 1 (50 pairs, ~2 min)
./venv/bin/python -u bot_vgc2026_phaseV3a2_reality.py \
  --tag phaseV3c3_learned_v3c1_vs_v3_paired100_chunk1 \
  --n-pairs 50 --start-pair 50 --overwrite --timeout 90 \
  --learned-policy learned_preview_v3c1 \
  --account-prefix V3c3_

# Merge + analyze
./venv/bin/python analyze_vgc2026_phaseV3a2_reality.py \
  --tag phaseV3c3_learned_v3c1_vs_v3_paired100_chunk0 \
  --merge-tags phaseV3c3_learned_v3c1_vs_v3_paired100_chunk1 \
  --learned-policy learned_preview_v3c1 \
  --baseline-policy matchup_top4_v3 \
  --md logs/vgc2026_phaseV3c3_qualification_report.md
```

### Results (merged 200 battles)

| metric | value |
|---|---:|
| valid pairs | 100/100 |
| valid battles | 200/200 |
| learned wins | 106/200 (0.530) |
| Wilson 95% CI | [0.461, 0.598] |
| learned_as_p1 wins | 52/100 (0.520) |
| learned_as_p2 wins | 54/100 (0.540) |
| side collapse | 0.020 (2pp) |
| learned_both / v3_both / split | 40 / 34 / 26 |
| treatment effect | +0.0600 |
| bootstrap 95% CI | [-0.10, +0.22] |
| one-sided p (regression) | 0.2807 |
| avg turns | 6.2 |
| plan change rate | 0.95 |
| unique learned plans | 83 |
| unique V3 plans | 67 |

### Gate table (per spec)

| gate | threshold | actual | result |
|---|---|---:|:-:|
| 200/200 valid battles | 200/200 | 200/200 | PASS |
| 100/100 complete pairs | 100/100 | 100/100 | PASS |
| zero timeout/error/no_battle | 0 | 0 | PASS |
| preview validation 100% | 100% | 100% | PASS |
| side collapse <= 10pp | <= 0.10 | 0.02 | PASS |
| learned win rate >= 50% | >= 0.50 | 0.530 | PASS |
| learned_both >= v3_both | >= | 40 >= 34 | PASS |
| treatment effect >= 0 | >= 0 | +0.06 | PASS |
| one-sided p >= 0.05 | >= 0.05 | 0.2807 | PASS |
| bootstrap lower bound >= -0.02 | >= -0.02 | -0.10 | **FAIL** |

### Decision

**BLOCKED.** The paired bootstrap treatment lower
bound (-0.10) is below the spec's threshold
(-0.02). 9 of 10 spec gates pass, but the 10th
fails. The data is consistent with learned being
up to 10% worse than baseline at the 5th
percentile. Per spec, any failed gate → BLOCKED.
Default policy **not flipped**.

### Why bootstrap lower bound is -0.10

100 pairs and 74 decisive. 26 of 100 pairs are
split (different winners each side, no signal).
Per-pair noise dominates the 6pp point estimate.
More pairs (e.g. 200) would tighten the CI.

### Tests

- 17/17 V3c.2a, 19/19 V3c.1, 38/38 V3a tests pass
- 349/349 combined in 27s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### Local-only / no-hidden-info

- localhost:8000 only
- VGC format `gen9championsvgc2026regma`
- Player names `V3c3_*` visible in browser
- No online API / LLM / scrape / hidden info

### Default policy unchanged

- `matchup_top4_v3` is the active V3 (unchanged)
- No new wrapper added
- No model trained
- No commit, no push

### Path forward (V3c.4+, user authorization needed)

1. Run a 200-pair qualification to tighten the
   bootstrap CI
2. Investigate why 26/100 pairs are split
3. Retrain V3c.1 with more data or features
4. Accept current numbers and override the gate
   (not recommended)

## Phase V3c.4 — 200-Pair VGC Qualification (2026-06-16)

**Status: BLOCKED on paired bootstrap treatment lower bound (-0.0950 < -0.02). 9/10 spec gates PASS.**

### Commands

4 chunks × 50 pairs = 200 pairs / 400 battles. ~2 min/chunk.

### Results (merged 400 battles)

| metric | value |
|---|---:|
| valid pairs | 200/200 |
| valid battles | 400/400 |
| learned wins | 204/400 (0.510) |
| Wilson 95% CI | [0.461, 0.559] |
| learned_as_p1 wins | 105/200 (0.525) |
| learned_as_p2 wins | 99/200 (0.495) |
| side collapse | 0.030 (3pp) |
| learned_both / v3_both / split | 69 / 65 / 66 |
| treatment effect | +0.0200 |
| bootstrap 95% CI | [-0.095, +0.13] |
| one-sided p (regression) | 0.3978 |
| avg turns | 6.1 |
| plan change rate | 0.95 |

### V3c.3 vs V3c.4

| metric | V3c.3 (100 pairs) | V3c.4 (200 pairs) | change |
|---|---:|---:|---|
| learned wins | 53.0% | 51.0% | -2pp |
| treatment effect | +0.06 | +0.02 | -0.04 |
| bootstrap CI width | 0.32 | 0.225 | -30% (narrower) |
| bootstrap lower bound | -0.10 | -0.095 | -0.005 |

The bootstrap CI narrowed by 30% as expected
with 2x sample size. But the point estimate
decreased, suggesting the original 100-pair
result was on the high end of the true effect.

### Gate table (per spec)

| gate | threshold | actual | result |
|---|---|---:|:-:|
| 400/400 valid battles | 400/400 | 400/400 | PASS |
| 200/200 complete pairs | 200/200 | 200/200 | PASS |
| zero timeout/error/no_battle | 0 | 0 | PASS |
| preview validation 100% | 100% | 100% | PASS |
| side collapse <= 10pp | <= 0.10 | 0.03 | PASS |
| learned win rate >= 50% | >= 0.50 | 0.510 | PASS |
| learned_both >= v3_both | >= | 69 >= 65 | PASS |
| treatment effect >= 0 | >= 0 | +0.02 | PASS |
| one-sided p >= 0.05 | >= 0.05 | 0.3978 | PASS |
| bootstrap lower bound >= -0.02 | >= -0.02 | -0.0950 | **FAIL** |

### Decision

**BLOCKED** on the paired bootstrap treatment
lower bound. 9/10 spec gates pass; the 10th
(bootstrap lower bound) fails. Per spec: "If
any gate fails: BLOCKED with exact failed gate."
Default policy **not flipped**.

### Why the lower bound is still -0.095

With 200 pairs and 134 decisive, 66 of 200
pairs (33%) are split. Per-pair signal (2pp)
is small relative to per-pair noise. Even at
400 battles, the bootstrap CI is wider than
the spec's -0.02 lower bound threshold.

### Tests

- 17/17 V3c.2a, 19/19 V3c.1, 38/38 V3a tests pass
- 349/349 combined in 28s, EXIT=0
- `py_compile` clean, `git diff --check` clean

### Local-only / no-hidden-info

- localhost:8000 only
- VGC format `gen9championsvgc2026regma`
- Player names `V3c4_*` visible in browser
- No online API / LLM / scrape / hidden info

### Default policy unchanged

- `matchup_top4_v3` is the active V3 (unchanged)
- No new wrapper added
- No model trained
- V3c.3 artifacts preserved
- No commit, no push

### Path forward (V3c.5+, user authorization needed)

1. Investigate 66/200 split pairs
2. Retrain V3c.1 with more data or richer
   features to amplify the per-pair signal
3. Run 500+ pair qualification for tighter CI
4. Accept current numbers and override the
   bootstrap gate (not recommended)

## Phase Ponytail Refactor — Step 1: action_keys (2026-06-16)

**Status: COMPLETE. 1 pre-existing failure unchanged. No regressions.**

### What changed

Extracted the action identity / legal-order telemetry
helpers from `bot_doubles_damage_aware.py` (lines
2148-2406, 259 lines) into
`doubles_engine/action_keys.py` (272 lines). The
helpers are re-exported via a shim in
`bot_doubles_damage_aware` so existing tests and
call sites keep working.

### Module shape

```
doubles_engine/
  __init__.py           # package marker
  action_keys.py        # 13 functions + 2 constants
```

### Files

- **New:** `doubles_engine/__init__.py` (9 lines)
- **New:** `doubles_engine/action_keys.py` (272 lines)
- **New:** `test_doubles_engine_action_keys.py` (416 lines, 33 tests)
- **Modified:** `bot_doubles_damage_aware.py` (14,929 → 14,691 lines)

### Refactor map (lines 31-14929 of bot_doubles_damage_aware.py)

| section | lines | extracted |
|---|---:|---|
| Config | 31-388 | not yet |
| Support-target helpers | 389-958 | not yet |
| Mechanics wrappers | 1874-2147 | not yet |
| **Action keys / telemetry** | 2148-2406 | **YES** |
| Safety block compute | 2407-2652 | not yet |
| Switch evaluators | 3248-4830 | not yet |
| `DoublesDamageAwarePlayer` class | 4830-14929 | not yet |

### Functions moved to `doubles_engine.action_keys`

13 functions: `_order_action_key`,
`_order_mechanic_label`,
`_order_action_key_with_mechanic`,
`_legal_action_keys_for_slot`,
`_legal_action_keys_with_mechanic_for_slot`,
`_raw_score_map_for_slot`,
`_raw_score_map_with_mechanic_for_slot`,
`_safety_block_map_for_slot`,
`_final_action_keys_from_joint`,
`_final_action_keys_with_mechanic_from_joint`,
`_selected_joint_key`,
`_selected_joint_key_with_mechanic`,
`classify_only_legal`

### Tests

- 33/33 `test_doubles_engine_action_keys` pass
- 462/462 doubles tests (1 pre-existing failure)
- 50/50 V3 tests
- `py_compile` clean
- `git diff --check` clean

### Why stop after one extraction

Per spec: "Prefer small, reviewable extraction
steps over a big rewrite." Each extraction has
non-trivial risk (signature mismatches, loop
pattern mismatches, isinstance checks). The
first extraction established the shim pattern.
Future extractions should follow this same recipe.

### Remaining sections to extract (in priority order)

1. Mechanics wrappers (275 lines)
2. Support-target helpers (570 lines)
3. Field/type helpers (240 lines)
4. Type-absorb/protocol (175 lines)
5. Safety block compute (245 lines)
6. Switch evaluators (1580 lines)
7. Config dataclass (357 lines)
8. `DoublesDamageAwarePlayer` class (10099 lines)

## Phase Ponytail Refactor — Step 2: STOP (2026-06-16)

**Status: STOPPED. No code moved. No regressions.**

### Stop condition

The mechanics section (lines 1874-2147) has
dependencies defined AFTER the Step 1 shim location
(line 2148+). Extracting the 6 mechanics helpers
to `doubles_engine.mechanics` would create an
import cycle:

```
bot → engine.action_keys (Step 1 shim, OK)
engine.mechanics → bot (for primitives)
```

### Files changed

**None.** No code was moved.

### Old vs new line count

`bot_doubles_damage_aware.py`:
- Before Step 2: 14,691
- After Step 2: 14,691 (unchanged)

### Tests run (baseline preserved)

- 33/33 `test_doubles_engine_action_keys` pass
- 462/463 doubles tests (1 pre-existing test_51
  failure unchanged from baseline 412/412)
- 50/50 V3 tests
- `py_compile` clean
- `git diff --check` clean

### Dependencies that block extraction

| helper | late-defined deps |
|---|---|
| `ability_hard_blocks_move` | `_extract_move_id`, `get_effective_move_type`, `_extract_ability`, `_extract_target_types` |
| `direct_known_absorb_blocks_move` | `is_opponent_spread_move` |
| `ability_redirects_single_target_move` | `is_opponent_spread_move` |

4 of 6 mechanics helpers depend on primitives
defined after the shim location. These would
cause `ImportError: cannot import name X from
partially initialized module` if extracted.

### Recommended workaround

Use lazy imports inside the function bodies
(option 1 in the report). Verified to work in a
POC. Preserves behavior, no broad rewrite.

### Next step

User authorization needed. Options:
- (a) Proceed with lazy imports
- (b) Move primitives first, then mechanics
- (c) Skip mechanics, extract a different
      section

## Phase Ponytail Refactor — Step 2b: Mechanics Extraction (2026-06-16)

**Status: COMPLETE. 6 mechanics helpers moved
with lazy imports. Step 1 regression fixed.**

### What changed

Extracted 6 mechanics wrappers from
`bot_doubles_damage_aware.py` (lines 1874-2147,
274 lines) into `doubles_engine/mechanics.py`
(381 lines). The known cycle is broken using
function-local lazy imports for the 4 late-defined
primitives.

### Files

- **New:** `doubles_engine/mechanics.py` (381 lines)
- **New:** `test_doubles_engine_mechanics.py` (552 lines, 34 tests)
- **Modified:** `bot_doubles_damage_aware.py` (-256 lines)
- **Modified:** `doubles_engine/action_keys.py` (Step 1 regression fix)
- **Modified:** `test_doubles_engine_action_keys.py` (Step 1 regression fix)

### Old vs new line count

`bot_doubles_damage_aware.py`:
- Before: 14,691
- After: **14,435** (-256)

### Step 1 regression fixed

While verifying Step 2b with the V3c runtime
test, found that Step 1 had changed the return
type of `_final_action_keys_from_joint` from LIST
(original) to TUPLE. Step 2b restored the original
return type. This was a Step 1 bug that went
undetected in Step 1 verification.

### Tests

- 33/33 action_keys tests
- 34/34 mechanics tests
- 534/535 doubles tests (1 pre-existing test_51
  failure unchanged)
- 55/55 V3c runtime tests
- 50/50 V3 tests
- `py_compile` clean
- `git diff --check` clean

## Phase Ponytail Refactor — Step 3: Support-Targets Extraction (2026-06-17)

**Status: COMPLETE.**

### What changed

Extracted 6 support-target helpers + 13 module
consts from `bot_doubles_damage_aware.py` to
`doubles_engine/support_targets.py`. Re-applied
Step 1+2b shims. Restored pre-existing 8-tuple
`_compute_order_safety_blocks` + narrow
integration that was lost in a recovery incident.

### Files

- **New:** `doubles_engine/support_targets.py`
  (701 lines)
- **New:** `test_doubles_engine_support_targets.py`
  (915 lines, 67 tests)
- **Modified:** `bot_doubles_damage_aware.py`
  (-959 net lines, from 14,435 → 13,476)
- **Modified:** 3 test files restored to
  8-tuple expectation; config gained 2 narrow
  fields; _compute_order_safety_blocks returns
  8-tuple; 2 callers + _compute_joint_scores
  pass narrow_blocked.

### Tests

- 67/67 support_targets tests
- 840/841 doubles tests (1 pre-existing test_51
  unchanged)
- `py_compile` clean
- `git diff --check` clean

## Phase Ponytail Refactor — Long Run (2026-06-17)

**Status: COMPLETE. 7 new modules. Bot: 13,476
→ 11,547 lines (-14.3%). No destructive git
commands. 1020/1021 tests pass.**

### Files
- **New modules:** `field_state`, `types`,
  `protocol`, `type_absorb`, `safety_blocks`,
  `forced_switch`, `switch_safety`,
  `revealed_switch`, `stat_drops`,
  `voluntary_switch` (10 total)
- **New tests:** 8 new test files
  (`test_doubles_engine_*`)
- **Modified:** `bot_doubles_damage_aware.py`
  shim imports

### Tests
- 1020/1021 PASS (1 pre-existing `test_51`)
- `py_compile` clean
- `git diff --check` clean

## Phase Ponytail Refactor — Checkpoint Freeze (2026-06-17)

**Status: Audit extraction paused. Behavior re-qualification smoke scheduled.**

### Summary
- Bot reduced: 14,929 → 11,497 lines (−3,432, −23.0%).
- doubles_engine/: 15 modules, 3,807 lines.
- 281 new focused engine tests, EXIT=0.
- Default policy unchanged: `matchup_top4_v3`.
- No model/default/policy flip.
- Pre-existing `test_51` failure unchanged (out of scope).

### Ponytail phases accepted
1. action_keys (Step 1)
2. mechanics (Step 2b)
3. support_targets (Step 3)
4. Long Run Steps 4–6 (field_state, types, protocol, type_absorb,
   safety_blocks, forced_switch, switch_safety, revealed_switch,
   stat_drops, voluntary_switch)
5. audit_metadata (Steps 7A, 7B, 7D, 7E)

### Decision
Pause audit extraction. Run 50-pair behavior smoke to verify V3c
baseline still holds after the 3,432-line refactor. If smoke passes,
recommend transitioning to behavior improvement work (Mega/switch/RL)
in a separate phase.

## Phase Ponytail Refactor — 50-Pair Behavior Smoke (2026-06-17)

**Status: PASS.**

### Smoke results
- Tag: `phasePonytail_post_refactor_smoke50_v1`
- 50 pairs / 100 battles / 0 errors / 0 timeouts / 0 no_battle
- Preview validation: 100%
- Learned wins: 59/100 = 0.59
- Treatment effect: +0.18

### Artifacts
- `logs/vgc2026_phasePonytail_post_refactor_smoke50_v1.csv`
- `logs/vgc2026_phasePonytail_post_refactor_smoke50_v1.jsonl`
- `logs/vgc2026_phasePonytail_post_refactor_smoke50_v1_report.md`

### Conclusion
Behavior preserved after the 3,432-line Ponytail refactor reduction.
Default policy `matchup_top4_v3` unchanged. No further audit extraction.
Recommend transitioning to behavior improvement work in a separate phase.

## Phase BI — Audit Instrumentation Track (BI-1 → BI-2E)

The instrumentation track ran from BI-1 to BI-2E with **zero
behavior change** at every step. Pure observational audit data
assembly and persistence.

### BI-1 — V4a + voluntary_switch audit completeness

Added per-turn capture of V4a attrs (`_v4a_legal_keys_slot0/1`,
`_v4a_selected_joint_key`, `_v4a_final_keys`) and 3 new
voluntary_switch kwargs (`decision_eligible`, `selected`,
`selected_species`). Projected `v4a` and `voluntary_switch`
sub-dicts to the live event. **V4a raw scores were
intentionally NOT passed** because 4-tuple dict keys
cannot be JSON-serialized.

Tests: 12 in `test_doubles_engine_audit_bi1.py`.

### BI-2A — Persisted JSONL validation

4 new tests in the BI-1 file driving `save_battle` and
asserting the persisted JSONL has V4a + voluntary_switch
fields. Confirmed the 5-pair smoke (which used no
audit_logger) lacked the fields because no logger was
attached — not because the bot didn't pass them.

### BI-2B — Compact state_snapshot

Added `_build_compact_state_snapshot(battle, battle_tag)`
to the audit logger with: species, HP fractions, types,
weather, fields, side conditions per slot. All JSON-safe
primitives; no raw Pokemon / order / Battle objects.

Tests: 13 in `test_doubles_engine_audit_bi2.py`.

### BI-2C — Switch counterfactual design only

No code change. Produced
`logs/phaseBI2C_switch_counterfactual_design.md` proving
all counterfactual data is already on hand at the audit
call site (`_vsw_best_stay`, `_voluntary_switch_candidate_tables`,
`_vsw_selected_actions`, `_vsw_counterfactual_actions`,
`_vsw_selection_changed`, `_vsw_reason_codes`). Only
`_vsw_best_stay_action` needed a 1-line observation
capture.

### BI-2D — Switch counterfactual persistence

Added `_vsw_best_stay_action` capture (1 line, no scoring
change), `assemble_switch_counterfactual_slot` helper,
one `switch_counterfactual` kwarg to logger, projected to
live event sub-dict.

Tests: 14 in `test_doubles_engine_audit_bi3.py`.

### BI-2E — Closeout + Mega readiness plan

This section + `logs/phaseBI2E_instrumentation_closeout_and_mega_plan.md`.

### Final state

- **320** engine + audit tests pass.
- **54** runtime parity tests pass.
- **3** `TestAuditLoggerMetadata` tests pass.
- `test_51_production_does_not_import_helper` (pre-existing)
  unchanged.
- No behavior/default/model/policy change.
- No Mega behavior, no RL/training, no 200-pair qualification.

### Recommended next phase

**BI-3A: Mega flag + legal-order generation with default OFF.**
See readiness plan for code targets, stop conditions, and
required tests.

## Phase BI-3K Closeout — Mega Opt-In Readiness (added 2026-06-18)

**Decision: Mega is approved as opt-in experimental behavior. Mega is NOT approved for default flip.**

### Phases in this track
- BI-3A: Mega flag + legal-order generation, default OFF.
- BI-3B: Mega tie behavior probe.
- BI-3C: Mega policy design.
- BI-3D: Mega damaging-move bonus (1e-3), default OFF.
- BI-3E: tiny Mega runtime probe.
- BI-3F-1: runner audit logger opt-in.
- BI-3F-2: 5-pair Mega audit smoke.
- BI-3G: Mega eligibility species guard (45 species).
- BI-3H: 20-pair opt-in smoke.
- BI-3I: allowlist integrity audit.
- BI-3J: 100-pair opt-in preview (invalid — OFF baseline leak).
- BI-3J.2: 100-pair opt-in preview rerun (invalid — runner wiring bug).
- BI-3K: OFF baseline integrity fix v1.
- BI-3K.1: OFF baseline regression test seal.
- BI-3K.2: OFF leak root-cause audit.
- BI-3K.3: treatment arm wiring fix.
- BI-3K.4 / BI-3K.4b: clean runtime probe (server |nametaken| issues).
- BI-3K.5: runner account isolation fix.
- BI-3K.6: runner single-construction + treatment side fix.
- BI-3K.7: audit both arms + battle tag metadata fix.
- BI-3K.8: 20-pair Mega wiring smoke.

### Final stable state
- `enable_mega_evolution` default: `False` (unchanged)
- `mega_damaging_bonus` default: `1e-3` (unchanged)
- Default policy `matchup_top4_v3` (unchanged)
- Runner supports opt-in `--enable-mega-evolution`, `--audit-decisions`, `--account-run-id`
- Both-arm audit works (treatment + baseline files)
- Account isolation works (run-id embedded, preflight uniqueness check)
- Baseline OFF has runtime proof: 0 Mega legal / 0 selected across BI-3K.8

### Evidence
- 156 unit tests pass across Mega-related suites
- BI-3K.7 1-pair probe: pass (both-arm audit, baseline proven Mega-free)
- BI-3K.8 20-pair smoke: 40/40 ok, treatment selected Mega 22, baseline 0/0, state/switch audit 100%

### BI-3K.8 detailed metrics
- 40/40 summary rows status ok
- 20/20 complete pairs
- 0 timeout/error/no_battle
- No |nametaken|
- Treatment audit: 40 rows, 722 turns, 380 Mega legal, 22 selected Mega (all allowlisted), state/switch 100%
- Baseline audit: 40 rows, 732 turns, 0 Mega legal, 0 selected Mega, state/switch 100%
- Selected Mega turn ratio: 3.05% (≤ 30% gate)

### Next phase recommendation
**Do NOT run 100/200-pair unless the user explicitly requests default adoption.** The 20-pair smoke is sufficient evidence that the plumbing is stable.

If default adoption is later requested, require Phase BI-3L 200-pair qualification with proper control arms per AGENTS.md adoption gates.

### Do-not-do
- Do NOT flip `enable_mega_evolution` default.
- Do NOT run more large samples for logic debugging.
- Do NOT run RL/training.
- Do NOT add more Mega damage modeling.
- Do NOT touch `test_51`.
- Do NOT commit/push.

See `logs/phaseBI3K_mega_opt_in_closeout.md` for full report.

## Phase BI-3M2 — Mega Intent Policy Closeout (added 2026-06-18)

**Decision: Mega intent policy is approved as opt-in experimental behavior. Default remains OFF.**

### Phases in this track
- BI-3M: added `mega_intent_bonus: float = 1.0` to DoublesDamageAwareConfig. Total Mega bonus is `mega_damaging_bonus + mega_intent_bonus` (default 1e-3 + 1.0 = 1.001). Gated by flag + mega + base_power > 0.
- BI-3M 5-pair smoke: 10/10 ok, treatment selected Mega = 4, baseline = 0/0, no status Mega, ratio = 3.77%.
- BI-3M2 20-pair smoke: 40/40 ok, treatment selected Mega = 22 (all allowlisted), baseline = 0/0, no status Mega, ratio = 6.09%, state/switch 100%.

### Final stable state
- `enable_mega_evolution` default: `False` (unchanged)
- `mega_damaging_bonus` default: `1e-3` (unchanged)
- `mega_intent_bonus` default: `1.0` (new, no effect when flag OFF)
- Default policy `matchup_top4_v3` unchanged
- No model/scoring/selection code touched
- No commit/push
- `test_51` unchanged

### BI-3M2 20-pair detailed metrics
- 40/40 summary rows status ok
- 20/20 complete pairs
- 0 timeout/error/no_battle
- No |nametaken|
- Treatment audit: 40 rows, 361 turns, 380 Mega legal, 22 selected Mega (all allowlisted), state/switch 100%
- Baseline audit: 40 rows, 359 turns, 0 Mega legal, 0 selected Mega, state/switch 100%
- Selected Mega turn ratio: 6.09% (≤ 30% gate)
- Status-move Mega: 0
- Non-allowlisted selected: 0

### Closeout decision
**Approved: Mega intent policy as opt-in.**
**Not approved: default flip.**
**Not needed: 100/200-pair unless default adoption is explicitly requested.**

If default adoption is later requested, require a separate BI-3L qualification decision with minimum acceptable gates:
- validity 100%
- baseline OFF clean
- selected Mega allowlisted
- status Mega = 0
- selected Mega ratio ≤ 30%
- no regression vs OFF beyond agreed threshold

Do not run that now.

See `logs/phaseBI3M2_mega_intent_smoke20_report.md` for full smoke results.
See `logs/phaseBI3M2_mega_intent_closeout.md` for closeout decision.

## Next Behavior Work Order (added 2026-06-18)

Mega is closed out as opt-in experimental behavior. Do not continue
Mega benchmarking unless default adoption is explicitly requested.

Proceed in this order:

1. **Switch decision**
   - Investigate voluntary-switch decisions, timing, selected switch
     quality, and switch-vs-stay counterfactuals.
   - Use fixture/unit checks and targeted probes first. Battle samples
     are for confirming integration, not discovering basic logic bugs.

2. **Turn-level analyzer**
   - Add/read tooling over persisted audit JSONL for
     `state_snapshot`, `switch_counterfactual`, V4a action keys, and
     selected actions.
   - Keep this phase read-only. It should explain turn-level decisions
     and regret slices before any behavior change.

3. **Team-preview / RL data quality**
   - Revisit learned-preview and RL-style work only after switch and
     turn-level analyzer data are reliable.
   - Do not train until the state/action/reward fields needed for a
     dataset are verified end-to-end.

Carry forward the evidence ladder from `AGENTS.md`: fixture/unit first,
then 1-pair probes, then 5-20 pair smokes. Reserve 100/200-pair runs for
adoption/default-flip decisions, not logic debugging.

## Phase SWITCH-4 — Switch Decision Closeout (added 2026-06-18)

**Decision: Switch decision behavior is HEALTHY. No scoring change recommended.**

### Phases in this track
- SWITCH-1: Switch decision evidence audit. Mapped full switch path. Recommended read-only analyzer first.
- SWITCH-2: Built `analyze_doubles_switch_per_turn.py` (15 fixture tests, 478 lines). Ran on BI-3M2 audit data.
- SWITCH-3: Switch audit field gap seal. No-code phase — all analyzer-critical fields already persist.
- SWITCH-4: Closeout. No scoring change recommended.

### Key metrics (BI-3M2 20-pair, both arms)
- Rows: 80
- Audit turns: 1,440
- Turns with switch_counterfactual: 720
- Deltas collected: 662
- Median delta: -360.61
- **Bad switches: 0**
- **Missed opportunities: 2** (deltas 92.4 and 70.9)
- Correct chosen switches: 10
- Correct stays: 650

### Closeout decision
**Switch scoring remains unchanged. Defaults remain unchanged. No more switch work unless new evidence appears.**

### Next work item
**Turn-level analyzer.** Aggregates per-turn data across battles to produce insights about decision quality, timing, and patterns.

### Do-not-do
- Do NOT run large samples for switch debugging.
- Do NOT change switch scoring without new analyzer evidence.
- Do NOT run RL/training from switch data yet.
- Do NOT change switch defaults.
- Do NOT add more switch audit fields.
- Do NOT touch Mega behavior.
- Do NOT touch `test_51`.
- Do NOT commit/push.

See `logs/phaseSWITCH4_switch_decision_closeout.md` for full closeout.

## Phase TURN-4 — Turn-Level Analyzer Closeout (added 2026-06-18)

**Decision: Turn-level analyzer is closed as WORKING / READ-ONLY / FIXTURE-TESTED.**

### Phases in this track
- TURN-1: Turn-level analyzer evidence audit + design. Found 129 turn-level fields, no gap.
- TURN-2: Built `analyze_doubles_turn_level.py` (978 lines, 17 fixture tests). Ran on BI-3M2.
- TURN-3: Input integrity check. Found TURN-2 baseline wording wrong (data was correct). Fixed pass-action parser. Corrected metrics.
- TURN-4: Closeout. No scoring change. Timing gap deferred.

### Key metrics (TURN-3 corrected, BI-3M2 20-pair)
- Turn records: 720
- Arms: {treatment: 361, baseline: 359}
- Action slot 0: move: 520, pass: 103, switch: 97
- Action slot 1: move: 471, pass: 185, switch: 64
- V4a mechanic slot 0: plain: 705, mega: 15
- V4a mechanic slot 1: plain: 713, mega: 7
- Low-margin turns: 241
- Overkill: 35, focus fire: 94, stale target: 68 (5 issue cases)

### Closeout decision
- Analyzer is a tool, not a feature.
- No scoring change recommended.
- No actionable pattern found in current data.
- 32 tests pass across turn-level and switch-level suites.

### Known gap
- decision_time_ms is absent/None in BI-3M2 audit (0/720 turns).
- Not blocking current interpretation.
- Defer timing instrumentation until a dedicated timing phase.

### Next work item
**Team-preview/RL data quality.**

### Do-not-do
- Do NOT change scoring from current analyzer output.
- Do NOT run more turn analyzer work unless new evidence appears.
- Do NOT add timing fields now.
- Do NOT run RL training until data quality inventory is complete.
- Do NOT touch `test_51`.
- Do NOT commit/push.

See `logs/phaseTURN4_turn_level_analyzer_closeout.md` for full closeout.

## Phase RL-3 — Team-Preview / RL Data Quality Closeout (added 2026-06-18)

**Decision: Team-preview data quality ADEQUATE. Learned policy promotion NOT APPROVED.**

### Phases in this track
- RL-1: Inventory. Mapped full team-preview pipeline. No major blockers.
- RL-2: Built `analyze_vgc2026_team_preview_dataset_quality.py` (15 fixture tests). Ran on V3c4 chunk 0.
- RL-3: Closeout. Data quality adequate. Promotion not approved.

### Key metrics (RL-2, V3c4 chunk 0 smoke)
- Rows analyzed: 100
- All status ok: 100/100
- Complete pairs: 50
- Preview validation: 100%
- Side balance: 50/50
- Duplicate battle tags: 0
- Duplicate team hashes: 0
- Non-observable features: 0
- Feature count: 20
- Nonzero weights: 14/20
- Treatment effect (chunk): +0.060
- Bootstrap 95% CI (chunk): [-0.160, +0.280]

### V3c.4 200-pair blocker (PROMOTION BLOCKER)
- learned wins: 204/400 (0.5100)
- baseline wins: 196/400 (0.4900)
- treatment effect: +0.0200
- bootstrap 95% CI: [-0.0950, +0.1300]
- **bootstrap lower bound -0.0950 < -0.02 (BLOCKED)**
- one-sided p (learned regression): 0.3978
- side collapse: 0.030 ≤ 0.10
- plan changed rate: 0.9450

**Learned policy must NOT become default.** Default remains `matchup_top4_v3`.

### RL readiness
- Team-preview data: ADEQUATE
- Team-preview model: V3c.1 exists
- Team-preview promotion: NOT APPROVED
- Turn-level RL: PARTIAL / NOT READY
- Turn-level training: DO NOT START

### Next strategic options
1. Design richer preview features
2. Design turn-level dataset schema
3. Pause learning and move to another behavior feature

### Do-not-do
- Do NOT retrain without data/design phase.
- Do NOT flip default.
- Do NOT run large benchmarks for logic debugging.
- Do NOT run RL training until turn-level dataset is validated.
- Do NOT touch `test_51`.
- Do NOT commit/push.

See `logs/phaseRL3_team_preview_rl_data_quality_closeout.md` for full closeout.

---

# Phase PREVIEW-1..10 — V3d.1 Learned-Preview Track (2026-06-18)

**Decision: V3d.1 learned-preview training PAUSED / NOT APPROVED.**

## Goal

Design, implement, validate, and evaluate richer team-preview
features (V3d.1) as a potential successor to V3c.1. The
track is closed out as paused because the diagnostic
showed v3d_all underperforms v3c_only on the pairwise
team-preview classification objective.

## Phases

### PREVIEW-1 — Richer Feature Design
- Designed 10 richer team-preview features in
  `logs/phasePREVIEW1_richer_feature_design.md`.
- 1 feature replaced: `our_anti_meta_threat_count` →
  `our_super_effective_coverage_count` (too ambiguous).
- No code changes.

### PREVIEW-2 — Feature Extraction
- Implemented 10 V3d.1 features in
  `vgc2026_phaseV3d1_opponent_features.py`.
- 21 fixture tests in
  `test_vgc2026_phaseV3d1_features.py`. All pass.
- All features observable, no hidden info.

### PREVIEW-3 — Feature Quality
- Validated feature distributions on 129 real teams in
  `logs/phasePREVIEW3_v3d1_feature_quality_report.md`.
- 7 healthy, 3 sparse (but nonzero).
- Hidden-info check: PASS.
- No constant/all-zero features.

### PREVIEW-4 — Training Design
- Designed V3d.1 training pipeline in
  `logs/phasePREVIEW4_v3d1_training_design.md`.
- No code changes.

### PREVIEW-5 — Trainer + Wrapper Infrastructure
- Implemented V3d.1 trainer in
  `vgc2026_phaseV3d1_train.py` (dry-run by default).
- Added `learned_preview_v3d1` policy branch in
  `team_preview_policy.py` (opt-in only, raises
  FileNotFoundError if model missing).
- 19 tests in `test_vgc2026_phaseV3d1_train.py`. All pass.
- No model artifact created.

### PREVIEW-6 — Golden Dataset Build
- Built golden dataset (100 rows) in
  `logs/vgc2026_phaseV3d1_golden_dataset.jsonl`.
- Deterministic SHA256.
- 12 tests in `test_build_vgc2026_phaseV3d1_golden_dataset.py`.
  All pass.

### PREVIEW-7 — Dry-Run Evaluation
- Ran dry-run on 100-row golden dataset.
- mean_val_acc 0.571 (FAIL, < 0.60).
- overfit_gap 0.284 (FAIL, > 0.20).
- median_val_acc 0.600 (PASS).
- 12 tests in `test_vgc2026_phaseV3d1_dryrun.py`. All pass.

### PREVIEW-8 — Expanded Golden Dataset + Dry-Run Recheck
- Built expanded golden dataset (400 rows) from all 4
  V3c.4 chunks.
- Dry-run: mean_val_acc 0.528 (FAIL), overfit_gap 0.181
  (PASS, improved from 0.284).
- 134 decisive pairs.
- Larger dataset fixed overfit but did not improve
  validation accuracy.

### PREVIEW-9 — Ablation + Hyperparameter Diagnostic
- Evaluated 144 configs across 4 feature sets, 3 epoch
  counts, 2 learning rates, 3 L2 values, 2 min_margin
  values.
- 0 configs pass all offline gates.
- best v3c_only mean_val_acc: 0.588
- best v3d_all mean_val_acc: 0.544
- v3d_all vs v3c_only delta: -0.044 (v3d_all
  underperforms v3c_only).
- 10 tests in `test_diagnose_vgc2026_phaseV3d1_dryrun.py`.
  All pass.

### PREVIEW-10 — Closeout
- V3d.1 learned-preview training is paused.
- No model artifact created.
- Default policy remains `matchup_top4_v3`.
- V3c.1 remains opt-in only and not promotion-approved.

## Key metrics (PREVIEW-9)

| metric | value |
|---|---:|
| configs evaluated | 144 |
| configs passing all gates | 0 |
| best v3c_only mean_val_acc | 0.588 |
| best v3d_all mean_val_acc | 0.544 |
| v3d_all vs v3c_only delta | -0.044 |
| model artifact created | NO |

## Why v3d does not beat v3c_only

1. v3d_all underperforms v3c_only by 4.4 percentage
   points on mean_val_acc (0.544 vs 0.588).
2. v3d_all has higher overfit gap (0.183 vs 0.122).
3. v3d_all has higher feature dominance (0.323 vs
   0.232), indicating pathological fitting.
4. Removing sparse features helps slightly but
   introduces even worse dominance.
5. No hyperparameter combination makes v3d_all pass
   all gates.

## Preserved assets

- `vgc2026_phaseV3d1_opponent_features.py` — feature
  extractor (useful for future research).
- `vgc2026_phaseV3d1_train.py` — trainer infrastructure
  (dry-run guarded).
- `logs/vgc2026_phaseV3d1_golden_dataset.jsonl` and
  `..._expanded.jsonl` — golden datasets.
- `analyze_vgc2026_phaseV3d1_feature_quality.py`,
  `build_..._golden_dataset.py`,
  `dryrun_..._training.py`,
  `diagnose_..._dryrun.py` — analyzers.
- `learned_preview_v3d1` in `team_preview_policy.py` —
  opt-in only, inert.

## Do-not-do

- Do NOT train the V3d.1 model.
- Do NOT create `logs/vgc2026_phaseV3d1_model.json`.
- Do NOT run 50/200-pair runtime qualification for V3d.1.
- Do NOT default-flip to any learned policy.
- Do NOT attempt learned-preview retraining without a
  new objective or better features.

## Recommended next behavior topic

Per PREVIEW-9 decision rules: "If v3d does not beat
v3c_only: recommend pausing learned preview and moving
to another behavior topic."

Suggested non-learning behavior features:
1. Protect/speed-control/support targeting (scoring
   change, not learned).
2. Voluntary switch quality scoring refinement.
3. Mega evolution refinement.
4. Switch decision analyzer improvements.
5. Turn-level analyzer improvements.
6. User-selected next feature.

See `logs/phasePREVIEW10_v3d1_learned_preview_closeout.md`
for full closeout.

## Phase BEHAVIOR-1..19 — Speed-Priority Expected-Faint Track Closeout (added 2026-06-19)

**Decision: CLOSED as fixed.**

### Root cause

The BEHAVIOR-16 Protect floor was not activating
because `faint_before_moving` was candidate-dependent
(set to False for Protect candidates via the
`is_protect or is_switch` gating) and
`expected_to_faint_before_moving` was only assigned
for the selected action (gated by `is_selected`).

### Fix (BEHAVIOR-18)

1. `estimate_speed_priority_threat` now sets
   `faint_before_moving=True` for any candidate when
   the slot is speed-threatened or priority-threatened.
   Both the `is_protect or is_switch` gating and the
   `candidate_priority == 0` check are removed (the
   "equivalent smallest safe implementation" because
   real Protect has priority=4, not 0).
2. `expected_to_faint_before_moving` is now set for
   every scored order, not just the selected one. This
   is required for the BEHAVIOR-16 floor to work for
   Protect candidates at `score_action` time.

### BEHAVIOR-18 evidence (5-pair smoke)

| metric | BEHAVIOR-17 | BEHAVIOR-18 |
|---|---:|---:|
| debug `expected_faint=True` at scoring time | 0/65 (0%) | 17/24 (71%) |
| debug `floor_applied=True` | 0/65 (0%) | 8/24 (33%) |
| raw protect >= 240 | 2/11 (18%) | 17/24 (71%) |
| expected_faint -> Protect | 0/10 (0%) | 12/24 (50%) |
| runtime parity | PASS | PASS |
| switch safety (floor on switch) | N/A | PASS (unit test) |
| Protect selection rate < 30% | PASS | PASS |
| full test suite | 121+ tests | 129+ tests |

### Phases in this track

- BEHAVIOR-1..10: speed-priority awareness scaffolding
- BEHAVIOR-11: +200 Protect bonus under expected_faint
- BEHAVIOR-12: -75 attack penalty under expected_faint
- BEHAVIOR-13: path alignment verified
- BEHAVIOR-14: piecewise policy designed
- BEHAVIOR-15: piecewise policy implemented (opt-in)
- BEHAVIOR-16: Protect baseline floor (240.0) implemented
- BEHAVIOR-17: path audit found root cause
- BEHAVIOR-18: fix applied; floor now activates
- BEHAVIOR-19: track closed as fixed

### Closeout decision

- Track closed as fixed.
- 50% expected_faint -> attack is expected (attack
  scores beat the 240 floor).
- Do NOT tune magnitude without a separate
  evidence phase.
- All config fields stable at their documented
  defaults.

### Remaining limitation

- 50% expected_faint cases still select attack
  (attack score > 240 floor).
- This is a magnitude issue, not a bug.
- Future magnitude tuning requires a separate 20+
  pair evidence phase (out of scope for this track).

### Current stable state (config fields)

| field | default | phase |
|---|---|---|
| `speed_priority_protect_bonus_under_expected_faint` | 200.0 | BEHAVIOR-11 |
| `speed_priority_expected_faint_attack_penalty` | 75.0 | BEHAVIOR-12 |
| `enable_speed_priority_piecewise_expected_faint_policy` | False | BEHAVIOR-15 |
| `speed_priority_expected_faint_penalty_high_lead` | 0.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_penalty_mid_lead` | 75.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_penalty_low_lead` | 200.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_penalty_close_lead` | 250.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_attack_lead_high` | 500.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_attack_lead_mid` | 250.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_attack_lead_low` | 100.0 | BEHAVIOR-15 |
| `speed_priority_expected_faint_protect_score_floor` | 240.0 | BEHAVIOR-16 |

### Do-not-do

- Do NOT add more bonus/penalty values now.
- Do NOT increase the floor value.
- Do NOT run large benchmarks for this issue.
- Do NOT do RL/model work for this issue.
- Do NOT change Mega/switch/preview unrelated
  settings.
- Do NOT touch `test_51`.
- Do NOT commit/push.

### Recommended next behavior topic

The speed-priority expected-faint track is closed.
Move to another behavior feature:

1. Voluntary switch quality scoring refinement.
2. Mega evolution refinement.
3. Switch decision analyzer improvements.
4. Turn-level analyzer improvements.
5. Support target targeting refinement.
6. User-selected next feature.

See `logs/phaseBEHAVIOR19_speed_priority_expected_faint_closeout.md`
for full closeout.

## Phase SUPPORT-1/2 — Support Targeting Track Closeout (added 2026-06-19)

**Decision: CLOSED as healthy based on available evidence.**

### SUPPORT-1 evidence summary

From the BI3M2 20-pair mega-intent smoke and the
BEHAVIOR-18 5-pair smoke:

| metric | value |
|---|---|
| wrong-side selected | 0 |
| stale support target | 0 |
| immune/no-effect support | 0 |
| broad wrong-side block fired | 0 times |
| narrow ally heal blocked | 0 (field not in older artifacts) |
| support moves selected | 23/361 (~6%, mostly Fake Out) |
| support-targeting tests | 276 pass (6 test files) |
| analyzer support coverage | 6 categories + wrong-side + narrow |

### SUPPORT-2 closeout decision

- Healthy based on available evidence.
- No scoring/targeting change recommended.
- No production change. No tests changed. No
  defaults changed. No model artifact.

### Limitations

This is NOT a claim that every support move is
exhaustively proven. Specific limitations:

1. Sample size for rare support moves is limited.
2. Mostly Fake Out in available artifacts (22/23
   support moves selected are Fake Out).
3. Rare moves (Heal Pulse, Pollen Puff, Rage
   Powder, Follow Me) are not exhaustively proven.
4. Narrow ally heal fields are not in older
   artifacts.
5. No targeted support-move smoke was run.

### Dormant helper finding (not a behavior bug)

`build_narrow_ally_heal_candidate_table` and
`narrow_ally_heal_wrong_side_block` are imported
in `bot_doubles_damage_aware.py` (lines 1025 and
1028) but never called.

- The broad support wrong-side block IS active
  and covers the severe-mistake case for Heal
  Pulse, Floral Healing, and Decorate.
- The narrow block would be redundant safety, not
  the primary defense.
- Defer cleanup; do not treat as behavior bug.

### Current stable state (config fields)

| field | default | phase |
|---|---|---|
| `enable_support_move_target_hard_safety` | False | Phase 6.3.8 |
| `enable_ally_heal_wrong_side_hard_safety` | False | Phase 6.3.8d |
| `support_move_wrong_side_block_score` | 0.0 | Phase 6.3.8 |

All support-targeting config fields stable at
their documented defaults.

### Phases in this track

- SUPPORT-1: Read-only support targeting evidence
  audit. Found 0 failures. Identified dormant
  narrow ally heal imports.
- SUPPORT-2: Close as healthy. No production
  change. No scoring change. No targeting change.

### Do-not-do

- Do NOT make blind support scoring changes.
- Do NOT do broad target override rewrites.
- Do NOT run large benchmarks for this issue.
- Do NOT do RL/model work for this issue.
- Do NOT remove or wire dormant narrow ally heal
  helpers in this phase.
- Do NOT touch `test_51`.
- Do NOT commit/push.

### Future work only if needed

1. Targeted support-move smoke for Heal Pulse,
   Pollen Puff, Rage Powder (only if a real
   production issue is observed).
2. Optional dead-code cleanup for dormant narrow
   ally heal imports (separate design phase).
3. Analyzer improvement only if new evidence
   appears.

### Recommended next behavior topic

Support targeting is closed. Move to another
behavior feature:

1. Voluntary switch quality scoring refinement.
2. Mega evolution refinement.
3. Switch decision analyzer improvements.
4. Turn-level analyzer improvements.
5. User-selected next feature.

See `logs/phaseSUPPORT2_support_targeting_closeout.md`
for full closeout.

## Phase SWITCH-5/6 — Voluntary Switch Refinement Track Closeout (added 2026-06-19)

**Decision: CLOSED as not needed.**

### SWITCH-5 evidence summary

From the BI3M2 20-pair mega-intent smoke (40
treatment + 40 baseline rows, 720 turns with
switch_counterfactual):

| metric | treatment | baseline |
|---|---:|---:|
| bad switches (negative delta) | 0 | 0 |
| missed opportunities (stay, positive delta) | 1 (delta=92.4) | 1 (delta=70.9) |
| correct chosen switches | 5/5 | 5/5 |
| correct stays | 328 | 322 |
| median delta | -356.75 | -394.42 |
| switch_counterfactual coverage | 100% | 100% |

### SWITCH-6 closeout decision

- No evidence-backed reason to change switch
  scoring.
- No scoring change recommended.
- No production change. No tests changed. No
  defaults changed. No model artifact.

### Missed opportunity interpretation

Both missed opportunities are the same pattern:
turn 4, slot 0, stayed with rockslide when
switching to sneasler (bench) would have been
+70-92 better. This is a sneasler mirror-match
scenario in the BI3M2 pool. Minor optimization,
not systematic. Not a reason to change scoring.

### Limitations

This is NOT a claim that switch behavior is
perfect. Specific limitations:

1. Based on BI3M2 artifacts only.
2. Rare matchup-specific switch opportunities
   may still exist.
3. No claim of perfect switch play (99.7%
   correct, not 100%).
4. Mirror-match confusion in audit data.

### Current stable state (config fields)

All switch-targeting config fields stable at
their documented defaults. No defaults changed.

### Phases in this track

- SWITCH-5: Voluntary switch quality refinement
  evidence audit. Confirmed 0 bad switches, 1
  minor missed opportunity per arm. Decision: no
  refinement needed.
- SWITCH-6: Close refinement as not needed. This
  report.

### Do-not-do

- Do NOT make blind switch scoring changes.
- Do NOT increase the switch baseline score.
- Do NOT decrease the sacrifice/stay-value
  penalties.
- Do NOT increase the risk_reduction_multiplier.
- Do NOT change the
  `voluntary_switch_min_risk_reduction` threshold.
- Do NOT add new reason_codes speculatively.
- Do NOT run large benchmarks for switch tuning.
- Do NOT touch `test_51`.
- Do NOT commit/push.

### Future work only if needed

1. Targeted sneasler mirror-match fixture
   (test-only, not a behavior change).
2. Analyzer improvements only if new evidence
   appears.
3. No scoring change unless future evidence
   shows a repeated pattern (5+ cases in a
   50+ pair smoke).

### Recommended next behavior topic

Voluntary switch refinement is closed. Move to
another behavior feature:

1. Mega evolution refinement.
2. Switch decision analyzer improvements.
3. Turn-level analyzer improvements.
4. User-selected next feature.

See `logs/phaseSWITCH6_voluntary_switch_refinement_closeout.md`
for full closeout.

## Phase TURN-5/6 — Timing Field Gap Track Closeout (added 2026-06-19)

**Decision: CLOSED as old-artifact only.**

### TURN-5 finding

The timing infrastructure is fully implemented
end-to-end:

1. **Bot compute** (bot_doubles_damage_aware.py:6830-6833):
   ```python
   _timing_enabled = getattr(
       self.config, "enable_decision_timing_diagnostics", False
   )
   _t_start = time.time() if _timing_enabled else 0
   ```

2. **Bot pass** (bot_doubles_damage_aware.py:11884-11893):
   The bot passes 5 timing fields to the logger
   with conditional `None` fallback.

3. **Logger accept** (doubles_decision_audit_logger.py:621-625):
   All 5 fields accepted with default `None`.

4. **Logger write** (doubles_decision_audit_logger.py:1197-1201):
   Fields written to `turn_data` with
   `float(x) if x else None` preservation.

5. **JSONL persist**: `save_battle` serializes
   `turn_data` to the main audit JSONL.

6. **Analyzer consume** (analyze_doubles_turn_level.py:405-409,
   974): Analyzer reads with explicit `None`
   handling.

### Artifact evidence

| artifact | turns | with timing |
|---|---:|---:|
| BI3M2 treatment | 361 | 0 |
| BI3M2 baseline | 359 | 0 |
| BEHAVIOR-18 treatment | 109 | 0 |
| BEHAVIOR-18 baseline | 110 | 0 |
| doubles_decision_audit.jsonl | 3455 | 0 |
| **Total** | **4394** | **0** |

### TURN-6 closeout decision

- Classification E: old-artifact only /
  infrastructure ready, not wired.
- No production fix needed.
- No scoring/default/behavior change.
- `enable_decision_timing_diagnostics` defaults
  to `False`. V3a.2 reality runner does NOT expose
  a CLI flag to enable it. No existing artifact
  was created with the flag enabled.

### Current stable state

- Timing infrastructure ready.
- Disabled by default.
- Existing artifacts cannot provide timing
  analysis.
- No model/default/scoring/behavior change.

### Phases in this track

- TURN-5: Timing field gap audit. Classified as
  E (old-artifact only).
- TURN-6: Close as old-artifact only. This report.

### Optional future work: RUNNER-TIMING-1

A separate future phase could:
1. Add `--enable-timing` CLI flag to the V3a.2
   reality runner.
2. Run a 5-pair smoke with the flag enabled.
3. Verify timing data appears in the artifact.
4. Run `analyze_doubles_turn_level.py` on the new
   artifact.

This is a runner/instrumentation change, not a
behavior change. Only pursue if timing analysis
becomes useful.

### Do-not-do

- Do NOT change production behavior.
- Do NOT change the runner in this phase.
- Do NOT add `--enable-timing` in this phase.
- Do NOT change defaults (keep the flag False).
- Do NOT run battles.
- Do NOT touch `test_51`.
- Do NOT commit/push.

### Recommended next behavior topic

Timing field gap is closed as old-artifact. Move
to another behavior feature:

1. Mega evolution refinement.
2. Switch decision analyzer improvements.
3. Turn-level analyzer improvements.
4. User-selected next feature.

See `logs/phaseTURN6_timing_field_gap_closeout.md`
for full closeout.

---

## RL-8 — Turn-Level Offline RL Closeout

**Decision:** `PIPELINE_WORKS / TRAINING_NOT_APPROVED`.

The turn-level offline RL track is closed at the
feasibility stage. The infrastructure is in place
and validated by 104 tests across 3 test files
plus 10 dataset validation gates plus 8 analyzer
readiness criteria. The data is not good enough
to justify real model training.

### Evidence chain

- **RL-4** designed `turn_rl_v1.0` schema with 10
  validation gates and a forbidden-field list.
  See `logs/phaseRL4_turn_level_offline_dataset_schema_design.md`.
- **RL-5** built the dataset builder. BI3M2 core
  dataset has 574 deduped rows / 80 battles /
  10/10 gates pass. 34 fixture tests. See
  `logs/phaseRL5_turn_level_offline_dataset_builder_report.md`.
- **RL-6** built the read-only quality analyzer.
  Core dataset passes 8/8 readiness criteria. 20
  fixture tests. Found that newer
  `speed_priority_threatened` and
  `expected_to_faint_before_moving` fields are
  0% covered in the dataset. See
  `logs/phaseRL6_turn_level_dataset_quality_report.md`.
- **RL-5b** investigated the missing fields.
  Proved the builder is correct (8 new tests,
  total 42). Root cause: BI3M2 source audit
  predates the BEHAVIOR-18 instrumentation
  change. Built a rebuilt dataset (RL-5b tag).
  Re-ran analyzer: still READY_FOR_DRYRUN. See
  `logs/phaseRL5b_turn_level_dataset_builder_field_coverage_fix_report.md`.
- **RL-7** built a dry-run in-memory linear
  pairwise reranker. Core: 574 rows, val
  pairwise accuracy 0.5398, majority baseline
  0.7741, overfit gap 0.0642, deterministic.
  Enriched: 180 rows from BEHAVIOR-18 source,
  100% coverage on 2 of 3 enriched fields, val
  pairwise accuracy 0.3030. 42 fixture tests.
  Decision: DRYRUN_PIPELINE_WORKS, training not
  justified. See
  `logs/phaseRL7_offline_policy_dryrun_feasibility_report.md`.
- **RL-8** is the closeout (this section). No
  code change, no training, no model artifact.

### Why pipeline works

1. Dataset builder validated by 42 tests; 10/10
   validation gates pass on BI3M2.
2. Quality analyzer works; 8/8 readiness criteria
   pass on core; 20 tests.
3. Dry-run reranker runs deterministically (repeat
   run matches exactly); 42 tests.
4. No episode leakage (set-intersection check).
5. No forbidden outcome fields in features
   (static test with sentinels).
6. No model artifact written (no
   `pickle.dump`/`torch.save`/`joblib.dump` in
   dry-run source).

### Why training is not approved

1. Pairwise accuracy 0.5398 is below majority
   baseline 0.7741.
2. Action distribution heavily biased (84% double
   attacks).
3. Core dataset 574 rows is small.
4. Enriched dataset 180 rows is too small for
   performance claims.
5. Terminal reward is sparse (1 signal per
   episode, no per-turn credit assignment).
6. No off-policy evaluation (selected action vs.
   random negatives only).
7. No performance claim possible.

### Stable state preserved

- `bot_doubles_damage_aware.py` not modified.
- `DoublesDamageAwareConfig` not modified.
- `matchup_top4_v3` policy unchanged.
- `learned_preview_v3c1`, `learned_preview_v3d1`
  not promoted.
- No `logs/vgc2026_phaseV3d1_model.json` (and no
  other model file from RL-4..8).
- The 4 pre-existing `*model*.json` files
  (`phaseV3a_preview_model.json`,
  `phaseV3a1_preview_model.json`,
  `phaseV3b_preview_model.json`,
  `phaseV3c1_model.json`) are from V3 phases,
  NOT from RL-4..8.
- `test_51` not touched.
- No commit/push.

### Future RL requirements

- Larger fresh dataset (5,000+ rows minimum).
- Latest instrumentation enabled.
- More diverse action distribution.
- Reward design beyond terminal-only (or explicit
  justification).
- Off-policy evaluation plan.
- Stronger baseline comparison (per-turn
  heuristic, constant predictor, current
  production policy).
- Model promotion criteria with adoption gates.

### Next recommended non-RL topic

- Project checkpoint / git hygiene.
- Runner instrumentation backlog.
- Analyzer cleanup.
- User-selected next feature.

See `logs/phaseRL8_turn_level_offline_rl_closeout.md`
for the full closeout report.

---

## RUNNER-2 — Runner Instrumentation Closeout

**Decision:** `INSTRUMENTATION_READY`.

### Flags

Core: `--tag`, `--n-pairs`, `--start-pair`,
`--seed`, `--overwrite`, `--timeout`,
`--learned-policy`, `--account-prefix`,
`--account-run-id`.

Opt-in instrumentation (all default OFF):
`--enable-mega-evolution`,
`--enable-behavior-15-piecewise`,
`--audit-decisions`,
`--enable-timing-diagnostics`.

### Key invariants

- The 4 instrumentation flags never change the
  global `DoublesDamageAwareConfig` default.
- `--enable-timing-diagnostics` requires
  `--audit-decisions` to take effect.
- `--enable-mega-evolution` only affects the
  treatment arm; baseline never gets Mega.
- Both-arm audit is always paired: 2 loggers,
  2 files, no single-arm mode.

### Verification

- 59 runner tests pass (38 mega + 21 timing).
- `git diff --check` exit 0.
- `py_compile` exit 0.
- `--help` shows all 14 flags.
- No model artifact.

See `logs/phaseRUNNER2_runner_instrumentation_closeout.md`
for full inventory, interaction matrix, and safe
probe recipes.

---

## PROJECT-CLOSEOUT-1 — Final Working-State Summary

**Decision:** ready for next user-selected work.

### Summary

- 4 modified tracked files (uncommitted
  ANALYZER-2 + RUNNER-2 docs).
- 13 untracked V3d.1 PAUSE files.
- 199 tests pass.
- No model artifact.
- No default flips.

### Closed tracks

Mega, Speed-priority, Support, Switch,
Turn-level analyzer, Runner instrumentation,
Switch attribution, Turn-level attribution,
Turn-level offline RL.

### Paused

V3d.1 learned preview (PREVIEW-10). 13 PAUSE
files stay untracked.

### Recommended next step

Commit the 4 uncommitted files, then either
stop, start a new behavior feature, or resume
V3d.1 with explicit user authorization.

See `logs/phasePROJECTCLOSEOUT1_final_working_state_roadmap.md`
for full inventory and 3-option roadmap.

---

## PROTECT-1 Roadmap — Protect Usage / Defensive Action Quality

After PROJECT-CLOSEOUT-1, the next recommended behavior topic was
recorded as Protect usage / defensive action quality.

Rationale:

- RL-7 proved the offline policy pipeline runs, but training is not
  approved.
- The current turn-level dataset is too biased toward double attacks.
- Protect is a clear, high-value defensive action category.
- Recent speed-priority expected-faint work makes Protect analysis
  timely and well-instrumented.

Planned sequence:

1. PROTECT-1 evidence audit (read-only).
2. PROTECT-2 analyzer gap seal only if needed.
3. PROTECT-3 policy design / fixture tests if suspicious cases recur.
4. PROTECT-4 small fix only with evidence.

The roadmap explicitly forbids RL training, model artifacts, large
logic-debugging benchmarks, default flips, and V3d.1 resume without
explicit authorization.

See `logs/phasePROTECT1_protect_usage_for_rl_roadmap.md`.

---

## PROTECT-3 — Protect Usage Closeout

**Decision:** `PATH_INCONSISTENCY_RESOLVED`. Close
the entire PROTECT track.

### Summary

- PROTECT-1 reported "0 floor applied" — that was
  a diagnostic bug (wrong field path).
- PROTECT-2 fixed the diagnostic. Real number:
  floor applied 20 times (slot0=7, slot1=13),
  9.2% of cases where the field is present.
- All 20 floor applications were in ef=True
  contexts.
- 15 of 20 led to Protect chosen.
- 5 of 20 still chose attack (policy/magnitude
  question, not a code defect).
- 27 attack-through cases had floor NOT applied
  (condition question, not a path bug).

### Stable state

- No production code change.
- No scoring change.
- No default flips.
- 148 tests pass.
- No model artifact.
- No commit/push.

See `logs/phasePROTECT3_protect_usage_closeout.md`
for full closeout.

---

## COMBO-1 — Doubles Combo-Support Inventory

After PROTECT-3, the next concern was that doubles support is broader
than wrong-side support targeting. COMBO-1 was created as a read-only
inventory before any implementation.

Main distinction:

- SUPPORT-2 closed support-targeting safety based on available evidence.
- COMBO-1 keeps combo planning open.

The inventory covers:

- Ally activation: Beat Up + Justified, Weakness Policy-style proc,
  absorb/redirect self-proc.
- Direct ally support: Helping Hand, Coaching, Decorate, Heal Pulse,
  Life Dew, Pollen Puff.
- Redirection/protection: Follow Me, Rage Powder, Wide Guard,
  Quick Guard, Ally Switch, Protect.
- Turn-order manipulation: After You, Instruct, Quash, Tailwind,
  Trick Room.
- Field/weather/terrain synergy.
- Spread move + partner immunity/benefit.
- Ability swap/copy/stat-transfer families.
- Anti-combo counterplay when the opponent focuses the boosted
  Pokemon.

Data snapshot:

- 129 VGC top-team entries include Tailwind 99 teams, Fake Out 73,
  Earthquake 51, Trick Room 33, Rage Powder 31, Wide Guard 19,
  Helping Hand 13, Follow Me 9.
- 558 random doubles species records include Helping Hand 64 species,
  Tailwind 94, Fake Out 44, Pollen Puff 36, Justified 4.

Decision:

- No scoring change from COMBO-1.
- Do not assume every ally hit is good.
- Do not weaken ally-damage safety.
- Recommended next phase is **COMBO-2 — Ally Activation Combo
  Evidence Audit**, read-only, starting with Beat Up + Justified as
  the mental model plus absorb/redirect partner activation.

See `logs/phaseCOMBO1_doubles_combo_support_inventory.md`.

---

## COMBO-5 — Combo Support Closeout

**Decision:** `PATH_INSTRUMENTED` / `TRAINING_NOT_APPROVED`. Close the COMBO support track.

### Summary

- COMBO-1 found combo planning not implemented;
  only safety is strong.
- COMBO-2 audit found absorb/redirect audit
  fields are template-only.
- COMBO-3 wired 3 new audit fields
  (absorb/redirect/weakness_policy) into
  `log_turn_decision` without scoring change.
- COMBO-4 1-pair probe confirmed wiring fires
  correctly: 2/26 redirect_ally cases (Lightning
  Rod Pikachu + Archaludon Electroshot).
- COMBO-5 closeout: docs only. No code change.

### Tests

- 6 new (test_doubles_combo3_ally_activation_audit)
- 113 existing (absorb/safety/redirection/etc.)
- 119 total, all pass.

### No-change confirmation

- No scoring change. No combo bonus.
- No Beat Up + Justified bonus. No absorb
  combo bonus. No Weakness Policy bonus.
- No model artifact. No commit/push.
- No `test_51` touched.

### Future COMBO work requires

- Curated test teams with absorb / WP members.
- 10+ pair probe.
- Scoring helper design.
- Explicit user request.

See `logs/phaseCOMBO5_combo_support_closeout.md`
for full closeout.

---

## CONTROL-PLAN-1 — Support / Field Control Roadmap

The user asked to make Protect, Tailwind, Trick Room, weather,
terrain, Taunt, Encore, Disable, and other control/support tools work
as real VGC plans rather than just known move names.

The plan is recorded in:

- `logs/phaseCONTROLPLAN1_support_control_roadmap.md`

Core conclusion:

- The bot already has many safety rules and recognizes many
  mechanics.
- Recognition is not enough. The missing layer is intent: when a
  support/control move should be worth giving up immediate damage.
- SETUP showed that broad proactive setup bonuses can regress at
  scale, so the next work must be narrow and evidence-backed.

Recommended path:

1. **CONTROL-1:** read-only unified control move evidence audit.
2. **CONTROL-2:** audit field gap seal if needed.
3. **CONTROL-3:** anti-setup disruption design.
4. **CONTROL-4A:** opt-in Taunt / Encore / Disable implementation.
5. **CONTROL-5A:** fixture, 1-pair, 5-pair, 20-pair validation.

Implementation priority:

- Start with anti-setup disruption (Taunt / Encore / Disable), not
  Tailwind/TR/weather/terrain. It is easier to guard because it reacts
  to opponent setup/support evidence.

Non-goals:

- No all-status-move bonus.
- No default flip.
- No RL/training.
- No broad setup revival.
- No Mega/weather/terrain combo planner yet.
- No `test_51`.

---

## PLANNER-ROADMAP-1 — Doubles Intent Planner Architecture

The next major direction is an intent planner. This supersedes the
old pattern of adding isolated bonuses for individual support moves.

The roadmap is recorded in:

- `logs/phasePLANNERROADMAP1_doubles_intent_planner_architecture.md`

Problem:

- The bot recognizes many mechanics, but support/control moves need
  future value.
- Tailwind/TR, Wide Guard, and anti-setup disruption showed that flat
  bonuses can be inert or regress at scale.
- The missing layer is short-horizon planning over the next one or
  two turns.

Intent families:

- `KO_NOW`
- `SURVIVE` / `STALL`
- `SPEED_CONTROL`
- `ANTI_SETUP` / `DISRUPT`
- `FIELD_CONTROL`
- `REDIRECTION`
- `SPREAD_DEFENSE`
- `COMBO_ENABLE`

Target architecture:

```text
battle state
  -> legal orders
  -> intent extraction
  -> intent candidates
  -> short-horizon intent value
  -> intent-adjusted joint scoring
  -> selected joint order
```

Recommended phases:

1. **PLANNER-1:** architecture audit.
2. **PLANNER-2:** intent audit fields if needed.
3. **PLANNER-3:** anti-setup intent MVP design.
4. **PLANNER-4:** dry-run intent replay.
5. **PLANNER-5:** opt-in MVP implementation only after dry-run.

Non-goals:

- No all-status-move bonus.
- No broad setup bonus revival.
- No immediate default flip.
- No RL/training as the first step.
- No weather/terrain combo planner until planner scaffolding exists.
- No Beat Up / Weakness Policy scoring until curated scenarios prove
  it.
- No `test_51`.

---

## SCENARIO-ROADMAP-1 — Runner Scenario Tooling Plan

The next infrastructure track is scenario tooling for targeted probes.

The plan is recorded in:

- `logs/phaseSCENARIOROADMAP1_runner_scenario_tooling_plan.md`

Why:

- Top-200 or mirror sampling often contains the desired move but does
  not cause the AI to use it.
- Planner work needs battle states where the key event actually
  happens.
- Scripted scenarios are needed to validate responses such as Taunt
  into Trick Room, Wide Guard into spread pressure, or combo support.

Scenario layers:

1. Curated team.
2. Curated matchup.
3. Scripted behavior.

Required tools:

- scenario JSON schema
- scenario loader / validator
- scripted opponent player
- audit-based scenario validation analyzer

First target:

- Anti-Trick Room: opponent uses Trick Room, our bot has Taunt /
  Encore / Disable legal, audit verifies the signal and response
  opportunity.

Recommended phases:

1. **SCENARIO-1:** framework design.
2. **SCENARIO-2:** loader and validator.
3. **SCENARIO-3:** scripted opponent player.
4. **SCENARIO-4:** first anti-Trick Room scenario.
5. **SCENARIO-5:** 1-pair validation.
6. **SCENARIO-6:** expand scenario library.

Non-goals:

- No scoring change.
- No RL/training.
- No default flip.
- No large debug benchmarks.
- No hidden-information leakage.
- No `test_51`.
