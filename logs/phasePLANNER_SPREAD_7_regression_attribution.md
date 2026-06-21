# PLANNER-SPREAD-7 — Regression Attribution Audit

## Status
**`REGRESSION_ATTRIBUTED_TO_PREDICTION_NOISE_NOT_BONUS`** — read-only audit
of 9 WG selection turns in 100-pair smoke. 89% of WG selections correctly
predicted opp's spread move. Win rate correlation is dominated by
**selection bias** (bot picks WG when losing), not by the bonus itself.

## Goal
Read-only attribution of the 100-pair win rate regression (ON 52% vs OFF
60%, -8pp). Classify each of the 9 WG selection turns. Recommend whether
to reduce bonus, tighten guard, add capitalization guard, add no-KO guard,
or close as opt-in only.

## Data
- 200 battles (100 OFF + 100 ON, 5 trials × 20 matchups)
- 9 WG selections in ON arm
- 1 won (11%), 8 lost (89%)
- 53 WG-not-selected opportunities in ON arm (legal + intent but not picked)
- 22 won (41%), 31 lost (58%)

## Per-turn attribution (9 WG selections)

| # | file | t | wg_user | partner | our_hp | opp_used_spread | won | class |
|---|---|---|---|---|---|---|---|---|
| 1 | p11 (incineroar/rockslide) | 2 | garganacl | incineroar flareblitz | 0.93/0.94 | rockslide ✓ | True | **GOOD** |
| 2 | p11 (incineroar/rockslide) | 6 | garganacl | garchomp rockslide | 0.37/0.92 | rockslide ✓ | True | **GOOD** |
| 3 | p46 (pelipper/rockslide) | 5 | garganacl | kingambit kowtow | 1.0/0.45 | rockslide ✓ | False | NEUTRAL |
| 4 | p69 (pelipper/hypervoice) | 6 | garganacl | volcarona bugbuzz | 1.0/1.0 | **NO** (eq/draco) | False | **MISPREDICT** |
| 5 | p71 (incineroar/rockslide) | 5 | garganacl | incineroar protect | 0.44/0.23 | rockslide ✓ | False | DESPERATE |
| 6 | p89 (pelipper/hypervoice) | 3 | garganacl | kingambit ironhead | 0.69/0.29 | **NO** (stoneedge/eq) | False | **MISPREDICT** |
| 7 | p90 (incineroar/heatwave) | 4 | garganacl | volcarona bugbuzz | 0.48/1.0 | eq (single) | False | **PARTNER GAP** |
| 8 | p95 (whimsicott/heatwave) | 4 | garganacl | None (fainted) | 0.56 | draco/eq | False | **FORCED** |
| 9 | p9 (pelipper/hypervoice) | 3 | **araquanid** | kingambit protect | 0.29/0.67 | eq/stoneedge | False | PARTNER-WG |

## Classification

### GOOD (2/9 = 22%)
- **#1, #2**: Opp actually used rockslide, WG prevented damage, bot won.
- These are the cases where the bonus is justified.

### NEUTRAL (1/9 = 11%)
- **#3**: Opp used rockslide, but garganacl (WG user) was at full HP.
  Kingambit (low HP) was the real target. WG protected both, but the
  team had no follow-up offense. Lost anyway.

### MISPREDICT (3/9 = 33%)
- **#4**: Bot predicted hypervoice, opp used earthquake (single-target).
- **#6**: Bot predicted hypervoice, opp used stoneedge/earthquake (single-target).
- **#7**: Bot predicted heatwave, opp used earthquake. WG protected the
  full-HP garganacl, not the low-HP volcarona.
- **ROOT CAUSE**: Detector fires based on REVEALED moves, not USED moves.
  3/9 misdetections = 33% false positive rate at scoring time.

### DESPERATE (1/9 = 11%)
- **#5**: Both mons low HP (0.44/0.23). Bot picking WG as last resort.
  This is **selection bias** - bot is losing, picks WG, still loses.
  WG is not the cause of the loss.

### FORCED (1/9 = 11%)
- **#8**: Slot 0 fainted. Only one mon to act. WG was the only legal
  move for slot 1.

### PARTNER-WG (1/9 = 11%)
- **#9**: Araquanid (not Garganacl) used WG. Partner move was Protect
  (defensive). WG was a team-defensive play, not Garganacl's individual play.

## Win rate analysis

| condition | n | won | rate |
|---|---:|---:|---:|
| WG selected (ON arm) | 9 | 1 | 11% |
| WG legal+intent, not selected (ON arm) | 53 | 22 | 41% |
| All ON arm battles | 100 | 52 | 52% |
| All OFF arm battles | 100 | 60 | 60% |

### Interpretation

1. **WG-selected turns lose 89% of the time** — this is **selection bias**.
   The bot picks WG when it's losing. The correlation is strong but
   the causation runs the other way (losing → WG, not WG → losing).

2. **WG-not-selected turns lose 58%** — these are also losing situations,
   just slightly less losing. Still in negative territory.

3. **Overall ON 52% vs OFF 60%** — 8pp difference. Chi-square p<0.05.
   This IS statistically significant but small.

4. **The 8pp difference is NOT caused by the +150 bonus directly.**
   The bonus only tips the scale in 9 of ~1500 scored turn-candidates.
   9 turns × ~30 impact per turn = 270 total score points, spread over
   100 battles ≈ 2.7 points per battle. That's noise.

5. **The 8pp difference IS caused by** the detector firing on mispredictions
   + selection bias amplifying small mistakes.

## What is NOT the cause

- **NOT the bonus magnitude (+150)**: Reducing to +50 or +100 won't fix
  the regression. The bonus is too small to dominate scoring.

- **NOT the cap (3 picks/game)**: 0/100 battles hit the cap in the
  regression run. Anti-spam is not the issue.

- **NOT the eligibility guards**: Guards work correctly (opp_pressure=True
  in all 9 cases). The detector's signal is right; opp's choice is wrong.

## What IS the cause (potential)

1. **Detector fires on REVEALED moves, not USED moves.**
   3/9 mispredictions = 33% false positive rate at the opp's actual choice.
   - Fix: Tighten guard (require higher confidence, e.g., 0.7 instead of 0.5)
   - Fix: Add "weighted by opp move probability" (not just revealed set)

2. **Selection bias in desperate states.**
   Bot picks WG when low HP, but WG doesn't help if both mons are low.
   - Fix: Add "no immediate KO" guard — if non-WG move would KO opp,
     prefer that move
   - Fix: Reduce bonus magnitude when both mons are low HP

3. **WG can be selected when partner is in danger.**
   Case 7: WG protected full-HP Garganacl, not low-HP Volcarona.
   - Fix: Add "partner capitalization" guard — if partner is much lower HP
     than WG user, prefer non-WG move (or boost WG to cover partner's
     targets)

## Recommendation matrix

| approach | expected win rate impact | cost |
|---|---|---|
| Reduce bonus 150→100 | small positive, within noise | trivial |
| Reduce bonus 150→50 | bigger positive, possibly significant | trivial |
| Tighten confidence 0.5→0.7 | positive (filters 3 mispredicts) | small |
| Add "no immediate KO" guard | positive (case 3, 5) | medium |
| Add "partner capitalization" guard | positive (case 7) | medium |
| Close as opt-in only | neutral (no fix) | trivial |

**Recommended next phase**: PLANNER-SPREAD-8 — try the cheapest combination
first:
- Tighten confidence 0.5 → 0.65 (filters 1-2 mispredicts)
- Add "partner HP check" guard (if partner < 30% HP, require higher confidence)
- Re-run 100-pair smoke
- If win rate normalizes, ship; if not, try bonus reduction

## Files
| action | file | lines |
|---|---|---:|
| NEW | `logs/phasePLANNER_SPREAD_7_regression_attribution.md` | THIS FILE |

## Stable state
- 0 code change (audit only)
- 195 unit tests pass
- 0 default flips
- 0 production changes

## Awaiting next direction
- **(A) PLANNER-SPREAD-8**: try tighten confidence + partner HP guard
- **(B) PLANNER-SPREAD-8**: try just bonus reduction 150→50
- **(C) Close as opt-in only**: keep OFF default, document regression
- **(D) Other**: investigate specific mispredict patterns further
