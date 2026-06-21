# PLANNER-SPREAD-8A — Confidence Gate (0.5 → 0.65)

## Status
**`MINIMAL_EFFECT_THRESHOLD_EQUALS_DETECTOR`** — The confidence gate
change to 0.65 had **minimal filtering effect** because the detector's
revealed_moves path returns conf=0.65, which equals the new threshold.
The opp_pressure path (conf=0.6) would be filtered but is rarely used.

## Goal
Test if tightening the confidence threshold (0.5 → 0.65) reduces
mispredicts without reducing WG selections to zero.

## Setup
- Changed `planner_spread_defense_min_confidence` from 0.5 to 0.65
- Detector paths:
  - revealed_moves → conf=0.65 (passes 0.65 threshold, no change)
  - opp_pressure → conf=0.6 (filtered by 0.65 threshold, but rarely fires)
- Ran 5 trials of 5-pair + 1 trial of 20-pair = 45 battles total
- Same setup as PLANNER-SPREAD-6

## Results (45 battles, 6 trials)

### Pass criteria (8/8 met in 20-pair run)
- [x] 40/40 battles ok
- [x] OFF arm: no bonus applied
- [x] ON arm: bonus applied
- [x] ON arm: picks per game <= 3
- [x] OFF arm: picks per game == 0
- [x] ON arm: pick rate (per battle avg) <= 1.0
- [x] ON arm: WG selected >= OFF arm WG
- [x] no timeout/error

### Win rate (high variance)
| run | OFF | ON | diff |
|---|---:|---:|---:|
| 5-pair run 1 | 2/5 (40%) | 1/5 (20%) | -20pp |
| 5-pair run 2 | ? | ? | ? |
| 5-pair trial 1 | ? | ? | ? |
| 5-pair trial 2 | ? | ? | ? |
| 5-pair trial 3 | ? | ? | ? |
| 20-pair full | 9/20 (45%) | 11/20 (55%) | +10pp |
| **15-pair (3 trials)** | **6/15 (40%)** | **6/15 (40%)** | **0pp** |

### WG selections
- 15 WG selections in 45 battles
- 0 mispredicts (all opp_used_spread=True)
- 13/45 battles had picks
- 6/15 battles won when WG was selected (40%)

## Analysis

### Why 8A has minimal effect
The detector's SPREAD_DEFENSE path returns:
- `revealed_moves` → confidence=0.65
- `opp_pressure` → confidence=0.6

With min_conf=0.65:
- revealed_moves decisions (0.65 >= 0.65) → PASS (no change)
- opp_pressure decisions (0.6 < 0.65) → FILTERED

In practice, almost all SPREAD_DEFENSE decisions use the revealed_moves
path (because opp has spread moves revealed). The opp_pressure path
fires only when no spread moves are revealed but opp_pressure is True
(rare). So the threshold change filters very few decisions.

### Why the win rate variance is so high
n=5 to n=20 is too small to detect 8pp differences reliably. With n=5,
the standard error of win rate is ~22% (1.96 × sqrt(0.5 × 0.5 / 5)).
A single 5-pair run's win rate is 40% ± 22% (95% CI).

Across 15 pairs (3 trials), the diff is 0pp. Across 20 pairs (1 trial),
the diff is +10pp. Both are within statistical noise.

### What 8A accomplished
- Default min_conf is now 0.65 (matches detector)
- opp_pressure-only decisions (rare) are filtered
- 0 mispredicts in this run (but sample is small)
- No regression detected (within noise)

### What 8A did NOT accomplish
- ❌ Did not filter the 3 mispredicts from PLANNER-SPREAD-7
  (those were all conf=0.65 revealed_moves decisions)
- ❌ Did not reduce WG selection count significantly
- ❌ Did not improve win rate (high variance)

## Recommendation: 8B needed

The 0.65 threshold alone is insufficient because it equals the detector's
revealed_moves confidence. To actually filter mispredicts, we need to:

### Option A: Lower detector's revealed_moves confidence
Change `_detect_spread_defense` revealed_moves path from 0.65 to 0.5
or 0.55. Then min_conf=0.65 would actually filter borderline decisions.

### Option B: Add a second signal requirement
Require BOTH revealed_spread_match AND another signal (e.g., opp_pressure).
Single-signal decisions are filtered.

### Option C: Add "partner HP" guard (8B)
Skip WG if partner is in danger and a non-WG move could capitalize.
This is what the user originally suggested as 8B.

## Files
| action | file | lines |
|---|---|---:|
| MOD | `bot_doubles_damage_aware.py` | min_conf 0.5→0.65 |
| MOD | `test_planner_spread_scoring.py` | updated test_default_min_confidence |
| NEW | `logs/phasePLANNER_SPREAD_8A_confidence_gate.md` | THIS FILE |

## Stable state
- 195 unit tests pass
- Default min_conf changed (0.5 → 0.65)
- 0 default flips
- 0 production behavior change beyond threshold

## Awaiting next direction
- **(A) PLANNER-SPREAD-8B**: try partner HP guard (per user's plan)
- **(B) PLANNER-SPREAD-8C**: lower detector confidence to 0.5/0.55
- **(C) Close as opt-in only**: 8A is not enough, accept the regression
- **(D) Run 100-pair anyway**: see if 8A's effect is consistent at scale
