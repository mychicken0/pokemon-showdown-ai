# PLANNER-SPREAD-10B — Deterministic Paired Harness

## Status
**`PAIRED_HARNESS_WORKS_NO_DIFFERENCE_DETECTABLE`** — 50 paired trials
(5 matchups × 10 trials). Bootstrap 95% CI for paired delta: [-0.20, +0.16].
Sign test: p=1.0. The ON arm is NOT statistically better or worse than OFF.

## Goal
Build a deterministic paired harness that controls for variance. Run ON
and OFF in paired trials (same matchup, same trial, alternating order)
and compute paired deltas with bootstrap CI.

## Setup
- 5 matchups × 10 trials = 50 paired battles
- Same teams (our, opp) for both arms
- Same trial number is the pairing key
- Alternating ON/OFF order per trial (control for first-mover bias)
- Pairing by trial index (not by RNG seed - poke-env doesn't support
  seed control)

## Results (50 paired trials)

### Per-matchup paired delta (ON wins - OFF wins)
| matchup | ON+ | OFF+ | ties | total | delta |
|---|---:|---:|---:|---:|---:|
| arcanine_vs_heatwave | 3 | 5 | 2 | 10 | -2 |
| arcanine_vs_hypervoice | 2 | 4 | 4 | 10 | -2 |
| incineroar_vs_snarl | 3 | 1 | 6 | 10 | +2 |
| pelipper_vs_rockslide | 1 | 0 | 9 | 10 | +1 |
| whimsicott_vs_dazzlinggleam | 1 | 1 | 8 | 10 | +0 |

### Aggregate (50 paired trials)
- ON wins: 10 (20%)
- OFF wins: 11 (22%)
- Ties: 29 (58%)
- Mean paired delta: -0.020
- Bootstrap 95% CI: [-0.200, +0.160]
- Sign test: ON won 10/21 = 0.48, p=1.000

### Statistical verdict
**ON-OFF diff is NOT statistically distinguishable from 0.**
The 95% CI includes 0. The sign test p-value is 1.0. We cannot reject
the null hypothesis that ON and OFF are equivalent.

### WG selections (ON arm)
- 6 WG selections in 50 battles (12% rate)
- 0 mispredicts (0% FPR)
- 2 won when selected (33% win rate)

## Comparison to previous runs

| run | n_battles | ON wins | OFF wins | diff | sig? |
|---|---:|---:|---:|---:|---|
| 8B 100-pair | 100 | 63 | 53 | +10pp | borderline |
| 9 targeted 100-pair | 100 | 49 | 65 | -16pp | sig |
| 10B 50 paired | 50 | 10 | 11 | -2pp | NOT sig |

The 10B paired result is the most reliable:
- 50 paired trials vs 100 unpaired
- Bootstrap CI vs point estimate
- Sign test vs aggregate win rate
- Mixed per-matchup vs aggregate

The 10B result suggests the true effect is near 0, and the 8B/9 swings
were variance, not real signal.

## Why 29 ties?

The 29 ties (both win or both lose) suggest that:
1. The matchup outcome (which team wins) dominates
2. The ON/OFF difference is small relative to the matchup noise
3. When the matchup is decided, the ON/OFF choice rarely matters

This is the **fundamental finding**: in 50 paired trials, 58% of the
time both arms get the same result. The ON/OFF difference only shows
up in the remaining 42%, and within that 42%, the split is
essentially random (10 vs 11).

## Recommendations

### Option A: Use 10B as the qualification standard
- 50 paired trials with bootstrap CI is a reliable measurement
- Result: ON arm is at best neutral
- **Recommendation: KEEP AS OPT-IN, do not default-flip**

### Option B: Run more matchups at 10B scale
- 5 matchups × 10 trials = 50 paired (current)
- 20 matchups × 10 trials = 200 paired (would be better)
- Trade-off: 2x runtime, 4x data

### Option C: Investigate specific matchups
- arcanine_vs_heatwave: -2 (OFF better)
- arcanine_vs_hypervoice: -2 (OFF better)
- These 2 matchups favor OFF. Why?
- Could lead to matchup-specific guards

### Option D: Accept current result
- ON arm is neutral
- Implementation is correct (0 mispredicts)
- Keep as opt-in

## Files
| action | file |
|---|---|
| NEW | `logs/phasePLANNER_SPREAD_10B_paired_harness.md` (THIS FILE) |
| NEW | `/tmp/opencode/paired_harness.py` (harness script) |
| NEW | 100 audit JSONL files (50 OFF + 50 ON) |

## Stable state
- 207 unit tests pass
- 0 code change (audit only)
- 0 default flip
- 0 production behavior change

## Awaiting next direction
- **(A) PLANNER-SPREAD-11**: extend to 20 matchups × 10 trials = 200 paired
- **(B) PLANNER-SPREAD-11**: investigate the 2 matchups favoring OFF
- **(C) PLANNER-SPREAD-11**: accept and keep as opt-in
- **(D) PLANNER-SPREAD-11**: try different design (e.g., confidence-based)
