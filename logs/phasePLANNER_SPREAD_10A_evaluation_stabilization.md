# PLANNER-SPREAD-10A — Evaluation Stabilization Plan

## Status
**`VARIANCE_DOMINATES_NO_CODE_REGRESSION`** — per-matchup analysis
shows 9/20 matchups changed sign (positive→negative or vice versa)
between 8B and 9 runs. OFF arm itself swung 12pp (53%→65%) between
runs with NO code change. The win rate difference is dominated by
randomness, not by code behavior.

## Goal
Find out why 8B was +10pp but 9 targeted was -16pp. Diagnostic only,
no code change.

## Findings

### 1. OFF arm itself swung 12pp between runs
| run | OFF wins | OFF rate |
|---|---:|---:|
| 8B 100-pair | 53/100 | 53% |
| 9 targeted | 65/100 | **65%** |
| diff | +12 | +12pp |

This is the SAME code (no scoring change). The OFF arm should be
stable. The 12pp swing is pure random noise.

### 2. Per-matchup analysis (20 unique matchups)
- 8B: 11 ON > OFF, 5 ON < OFF, 4 tied → ON wins 10 more
- 9: 4 ON > OFF, 11 ON < OFF, 5 tied → OFF wins 16 more
- **9/20 matchups changed sign** (positive in one run, negative in the other)
- This is HUGE variance for the same setup

### 3. WG selections: 9 has more (and more borderline)
| run | selections | mispredicts | win rate when selected |
|---|---:|---:|---:|
| 8B | 10 | 0 | 70% (7W/3L) |
| 9 | **21** | 1 | 48% (10W/11L) |

9 has 2x more WG selections. The 21 selections include:
- 13 "clearly low" (<0.5 HP) cases
- 7 "borderline" (0.5-0.7 HP) cases
- 1 "both high" (≥0.7) case (rare exception)

8B had 8 clearly low + 2 borderline. So 9 has more borderline cases
because the random trials happened to produce more "near-threat" states.

### 4. Per-matchup OFF arm variance
- 10 matchups where 9 OFF > 8B OFF (OFF won more in 9)
- 3 matchups where 9 OFF < 8B OFF
- 7 tied

The OFF arm itself fluctuates ±2-3 wins per matchup across runs.
With 5 trials per matchup, expected noise is ~1 win per matchup.

## Why 8B vs 9 differ so much

The fundamental issue: **100-pair has too much variance**.

Standard error for win rate at n=100: ~5%
8B's ON arm at 63% has 95% CI of [53%, 73%]
9's ON arm at 49% has 95% CI of [39%, 59%]

The CIs overlap heavily. The 14pp difference is within 1.5 sigma.
Statistically, we cannot conclude that ON arm is better or worse
than OFF arm based on a single 100-pair run.

The OFF arm's 12pp swing (53%→65%) is the smoking gun: same code,
random trials, large difference. The ON arm's 14pp swing (63%→49%) is
likely the SAME noise pattern, just on the other side.

## Recommendations

### Option A: Build a deterministic paired harness
- Use a fixed seed for poke-env
- Run ON and OFF in the same battle (impossible — they're different
  players in the same battle)
- OR run ON and OFF in IDENTICAL matchups with same team preview
- Then we can do true paired comparison (ON won / OFF won in same setup)

### Option B: Run many more 100-pair samples
- 5+ runs × 100 pairs = 500+ pairs
- Average the win rates to reduce variance
- More data = less noise

### Option C: Accept high variance, keep opt-in
- The current code is working as designed
- Variance is inherent to 100-pair runs with 5 trials each
- Don't default-flip; the signal is too noisy

## Decision label

**`VARIANCE_DOMINATES_NO_CODE_REGRESSION`** — 8B's +10pp and 9's -16pp
are both within expected variance. The code is correct, the noise
is dominating. Do NOT default-flip based on this signal.

## Pass criteria
- [x] 0/0/0 (no code change)
- [x] OFF arm itself is unstable (53→65) → variance is real
- [x] 9/20 matchups changed sign → random, not code
- [x] No pattern in which matchups favor ON vs OFF
- [x] Audit fields 100% (no corruption)

## Files
| action | file |
|---|---|
| NEW | `logs/phasePLANNER_SPREAD_10A_evaluation_stabilization.md` (THIS FILE) |

## Stable state
- 207 unit tests pass
- 0 code change
- 0 default flip
- 0 production behavior change

## Awaiting next direction
- **(A) PLANNER-SPREAD-10B**: build deterministic paired harness
- **(B) PLANNER-SPREAD-10B**: run 5+ 100-pair samples to average
- **(C) Close as opt-in for now**; revisit with more data
- **(D) Different approach**: focus on smaller, controlled tests
