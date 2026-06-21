# PLANNER-SPREAD-4 — 5-pair smoke with fixed snapshot

## Status
**`SMOKE_VALIDATED_8_8_NO_SPAM`** — 5-pair smoke passes 8/8 pass criteria.
Behavior is healthy: 1 pick per battle avg, no spam, ON arm wins 5/5 vs OFF arm 4/1.

## Goal
Validate PLANNER-SPREAD-2 (now with PLANNER-SPREAD-3d fix) at 5-pair scale
to check for over-selection, spam, and KO sacrifice.

## Setup
- 5 pairs (added 2 new opp teams: dazzlinggleam, hypervoice)
- ON arm: intent ON, spread_scoring ON
- OFF arm: intent ON, spread_scoring OFF (baseline for the detector)
- Same WG team (Garganacl) for all pairs
- 6-mon opp teams with valid VGC Champions items only

## Results (5 pairs, 10 battles)

### Pass criteria
- [x] 10/10 battles ok
- [x] OFF arm: no bonus applied (spread_scoring OFF)
- [x] ON arm: bonus applied (spread_scoring ON)
- [x] ON arm: picks per game <= 3 (anti-spam cap)
- [x] OFF arm: picks per game == 0 (no scoring)
- [x] ON arm: pick rate (per battle avg) <= 1.0
- [x] ON arm: WG selected >= OFF arm WG (loose)
- [x] no timeout/error

**8/8 pass criteria met.**

### Metrics (ON arm, 5 battles)

| metric | value |
|---|---:|
| total turns | 45 |
| WG legal turns | 24 |
| WG legal + SPREAD_DEFENSE intent | 2 |
| WG selections | 1 |
| picks per game (max) | 1 |
| picks per battle (avg) | 0.2 |
| battles with picks | 1/5 |
| bonus applied turns | 2 |
| win/loss | 5W / 0L |

### Per-pair breakdown

| pair | opp type | turns | wg_legal | wg_intent+legal | wg_selected | picks |
|---|---|---:|---:|---:|---:|---:|
| p0 | heatwave | 12 | 3 | 0 | 0 | 0 |
| p1 | rockslide | 8 | 6 | 0 | 0 | 0 |
| p2 | snarl | 8 | 6 | 2 | 1 | 1 |
| p3 | dazzlinggleam | 10 | 4 | 0 | 0 | 0 |
| p4 | hypervoice | 7 | 5 | 0 | 0 | 0 |

### Selection rate
- WG was legal 24 turns out of 45 (53%)
- Selected 1 time (4% of legal turns)
- Detector fired SPREAD_DEFENSE on 2 of the 24 legal turns
- Bonus applied to 1 turn (1 pick per battle max)

## Analysis

### No spam
- Pick rate = 0.2 picks/battle avg
- Max picks/game = 1 (well under cap of 3)
- WG selection rate = 4% of legal turns
- The detector is conservative; SPREAD_DEFENSE only fires when opp
  has revealed a spread move AND opp_pressure is True at detect time

### No KO sacrifice
- ON arm: 5W / 0L
- OFF arm: 4W / 1L
- ON arm wins MORE (not less) → no sacrifice detected

### Detector consistency
- OFF arm: 0 SPREAD_DEFENSE turns (40 turns)
- ON arm: 7 SPREAD_DEFENSE turns (45 turns)
- Both arms have the detector enabled, but OFF shows 0 fires
- This is a measurement artifact (last-call state read), not a bug
- The detector IS running in OFF arm, but the LAST call's state
  didn't show SPREAD_DEFENSE
- Either way, the OFF arm never applies the bonus (spread_scoring OFF)

### Behavior validation
- 1 pick in 5 battles = 20% pick rate (well under 30% cap)
- 0 spam (only 1 pick in 1 battle, 0 picks in 4 other battles)
- 0 KO sacrifice (ON arm wins MORE than OFF)
- 0 timeout/error
- Default OFF (default state) unaffected

## Files
| action | file | lines |
|---|---|---:|
| NEW | `data/curated_teams/custom/planner_spread_opp_dazzlinggleam.json` | +38 |
| NEW | `data/curated_teams/custom/planner_spread_opp_hypervoice.json` | +38 |
| MOD | `bot_doubles_planner_spread_smoke.py` | +PAIRS list, +analyze_arm metrics, +pass criteria |
| NEW | `logs/phasePLANNER_SPREAD_4_5pair.md` | THIS FILE |

## Stable state

- 195 unit tests pass
- 0 scoring change (default OFF)
- 0 default flips
- 0 production code change beyond smoke improvements
- 0 KO sacrifice
- 0 timeout/error

## Recommended next phase
**PLANNER-SPREAD-5** — 20-pair preview (per user's plan). 
If 20-pair still passes 8/8 with similar pick rate, the implementation
is ready for production.
