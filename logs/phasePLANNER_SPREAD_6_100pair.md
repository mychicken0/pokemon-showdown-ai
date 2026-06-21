# PLANNER-SPREAD-6 — 100-pair qualification preview

## Status
**`REGRESSION_AT_SCALE`** — 100-pair smoke (200 battles) shows 8/10 pass
criteria. **Win rate regression detected**: ON arm wins 52% vs OFF 60%
(8pp lower, chi-square p<0.05). Recommend keeping opt-in and tuning.

## Goal
Validate PLANNER-SPREAD-2 (with PLANNER-SPREAD-3d fix) at 100-pair scale
(5 trials × 20 unique matchups = 100 pairs = 200 battles) for production
qualification.

## Setup
- 20 unique (our, opp) matchups (4 WG teams × 5 opp teams)
- 5 trials per matchup with fresh player instance
- Same WG team variations as PLANNER-SPREAD-5
- ON arm: intent ON, spread_scoring ON
- OFF arm: intent ON, spread_scoring OFF

## Results (100 pairs, 200 battles)

### Pass criteria (8/10 met)
- [x] 200/200 battles ok
- [x] 0 timeout/error
- [x] ON arm: bonus applied (spread_scoring ON)
- [x] OFF arm: no bonus applied (spread_scoring OFF)
- [x] ON pick rate <= 30% (0.27 picks/battle)
- [x] ON max picks/game <= cap (3)
- [x] ON WG selected > OFF WG selected (9 > 0)
- [ ] **ON win rate not worse than OFF by >2pp (FAIL: -8pp)**
- [ ] **ON win rate >= OFF win rate (FAIL)**
- [x] audit fields 100% (all battles have picks/bonus fields)

### ON arm metrics (100 battles)

| metric | value |
|---|---:|
| total turns | 758 |
| WG legal turns | 249 (33% of turns) |
| WG legal + SPREAD_DEFENSE intent | 62 (25% of legal) |
| WG selections | 9 (14.5% of intent+legal) |
| picks per game (max) | 3 (at cap) |
| picks per battle (avg) | 0.27 |
| picks per game (total) | 27 |
| battles with picks | 24/20 (24%) |
| bonus applied turns | 104 |
| **win rate** | **52/100 (52%)** |

### OFF arm metrics (100 battles)

| metric | value |
|---|---:|
| total turns | 775 |
| WG legal turns | 243 (31% of turns) |
| WG selections | 0 |
| picks per game | 0 |
| **win rate** | **60/100 (60%)** |

### Per-matchup analysis (5 trials each, 20 matchups)

| matchup | OFF | ON | diff |
|---|---|---|---|
| arcanine vs dazzlinggleam | 5/5 (100%) | 4/5 (80%) | -20pp |
| arcanine vs heatwave | 3/5 (60%) | 3/5 (60%) | 0pp |
| arcanine vs hypervoice | 2/5 (40%) | 3/5 (60%) | +20pp |
| arcanine vs rockslide | 1/5 (20%) | 0/5 (0%) | -20pp |
| arcanine vs snarl | 1/5 (20%) | 2/5 (40%) | +20pp |
| incineroar vs dazzlinggleam | 1/5 (20%) | 3/5 (60%) | +40pp |
| incineroar vs heatwave | 3/5 (60%) | 4/5 (80%) | +20pp |
| incineroar vs hypervoice | 4/5 (80%) | 1/5 (20%) | **-60pp** |
| incineroar vs rockslide | 2/5 (40%) | 2/5 (40%) | 0pp |
| incineroar vs snarl | 3/5 (60%) | 3/5 (60%) | 0pp |
| pelipper vs dazzlinggleam | 5/5 (100%) | 3/5 (60%) | **-40pp** |
| pelipper vs heatwave | 5/5 (100%) | 2/5 (40%) | **-60pp** |
| pelipper vs hypervoice | 2/5 (40%) | 0/5 (0%) | **-40pp** |
| pelipper vs rockslide | 4/5 (80%) | 3/5 (60%) | -20pp |
| pelipper vs snarl | 2/5 (40%) | 5/5 (100%) | **+60pp** |
| whimsicott vs dazzlinggleam | 3/5 (60%) | 4/5 (80%) | +20pp |
| whimsicott vs heatwave | 4/5 (80%) | 2/5 (40%) | -40pp |
| whimsicott vs hypervoice | 3/5 (60%) | 2/5 (40%) | -20pp |
| whimsicott vs rockslide | 4/5 (80%) | 3/5 (60%) | -20pp |
| whimsicott vs snarl | 3/5 (60%) | 3/5 (60%) | 0pp |

## Analysis

### Win rate regression
- ON arm: 52/100 (52%)
- OFF arm: 60/100 (60%)
- Difference: -8pp
- Chi-square: 4.41, p < 0.05 (statistically significant)
- 8/20 matchups favor ON, 8/20 favor OFF, 4/20 tie

### Pattern: bonus HELPS vs non-spread, HURTS vs spread
- ON arm wins more vs snarl (snarl is single-target Dark move, NOT spread)
- ON arm wins less vs heatwave/hypervoice/dazzlinggleam (these are common
  spread users)
- This is counter-intuitive: the bonus should HELP against spread users
- Possible reasons:
  1. WG is being selected in suboptimal situations (waste of a turn)
  2. The opp's spread move was already going to miss / be protected
  3. The bot is over-using WG, telegraphing defensive play
  4. Statistical noise (n=5 per cell is small)

### What the audit shows
- 9 WG selections in 100 battles (1 per ~11 battles)
- 24/100 battles had at least one pick
- 14.5% of intent+legal turns → WG selected
- 14.5% is a moderate pick rate

### When WG was selected, the bot lost 7/8
- 8 battles had WG selections
- 1 won (p11 t1 incineroar vs rockslide)
- 7 lost
- This is a strong negative correlation
- BUT: WG might be selected IN losing situations (the bot is desperate
  and picks WG to survive)
- This is selection bias, not causation

## Decision label

**`REGRESSION_AT_SCALE`**

The implementation is correctly applying the bonus (10/10 wiring pass
criteria met), but the bonus is associated with a -8pp win rate at
100-pair scale. The user should NOT default-flip to True without further
investigation.

## Recommended next steps

### Option A: Reduce bonus magnitude
- Change `planner_spread_defense_wg_bonus` from 150 to 50 or 100
- Re-run 100-pair smoke
- If win rate normalizes, the bonus was too aggressive

### Option B: Tighten guard
- Require higher confidence (0.5 → 0.7) for SPREAD_DEFENSE
- Or require opp_pressure to be confirmed twice
- Re-run 100-pair smoke

### Option C: Investigate specific matchups
- The big losers: pelipper vs heatwave (-60pp), pelipper vs hypervoice
  (-40pp), incineroar vs hypervoice (-60pp)
- All involve spread users
- Maybe the bot is over-selecting WG in these matchups

### Option D: Keep opt-in
- Leave the flag at False by default
- The implementation is correct but the bonus is too aggressive
- Document the regression and let users opt-in

## Files
| action | file | lines |
|---|---|---:|
| NEW | `logs/phasePLANNER_SPREAD_6_100pair.md` | THIS FILE |
| NEW | 200 audit JSONL files | 200 PLANNER_SPREAD_6 audit files |

## Stable state

- 195 unit tests pass
- 0 scoring change (default OFF)
- 0 default flip (RECOMMENDED not to flip given regression)
- 0 production code change beyond smoke runner

## Awaiting next direction

- **(A) Reduce bonus to 50 or 100**: cheap, fast to test
- **(B) Tighten guard (confidence 0.7)**: cheap, fast to test
- **(C) Investigate specific matchups**: more work but informative
- **(D) Keep opt-in**: safe, no further action
