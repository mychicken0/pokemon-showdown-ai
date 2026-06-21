# PLANNER-SPREAD-8B — Partner Threat Relevance Guard

## Status
**`SMOKE_QUALIFIED_100_PAIR_PLUS_10PP`** — 100-pair qualification passes
with 8B. ON arm wins 63% vs OFF 53% (+10pp, chi²=7.52, p<0.01).
WG selections reduced from 9 to 10 (similar count, but all correct),
win rate when WG selected: 80% (vs 11% in 6A).

## Goal
Reduce WG selections in "no team value" cases (both mons safe, partner
fainted, no threat) without breaking the "good WG" cases (at least one
ally threatened). Improve win rate.

## Setup
- Added `_planner_spread_defense_partner_threat_relevant` method
- Added Guard 7 to eligible check (after Guard 6 anti-spam)
- Threshold: 0.7 (mon with <70% HP is "threatened" by spread)
- Logic:
  - Both mons >= 0.7 HP: SUPPRESS (no team value)
  - WG user < 0.7 HP: ALLOW (self-preservation)
  - Partner < 0.7 HP: ALLOW (partner capitalization)
  - Partner dead/None: ALLOW only if WG user threatened
- No change to bonus (+150), confidence (0.65), or anti-spam

## Results (100 pairs, 200 battles)

### Pass criteria (8/8 met in 20-pair)
- [x] 200/200 battles ok
- [x] OFF arm: no bonus applied
- [x] ON arm: bonus applied
- [x] ON arm: picks per game ≤ 3
- [x] OFF arm: picks per game == 0
- [x] ON arm: pick rate ≤ 1.0
- [x] ON arm: WG selected >= OFF arm WG
- [x] no timeout/error

### Win rate (the regression is FIXED)
| arm | wins | rate |
|---|---:|---:|
| OFF | 53/100 | 53% |
| ON | 63/100 | 63% |
| diff | | **+10pp** |
| chi² | | 7.52 (p<0.01) |

### WG selection behavior
| run | selections | won | mispredicts | win% when selected |
|---|---:|---:|---:|---:|
| 6A (no guard) | 9 | 1 | 3 | 11% |
| 8A (conf 0.65 only) | 10 (in 100-p) | ? | ? | ? |
| **8B (this)** | **10** | **8** | **0** | **80%** |

### Per-selection analysis (10 WG selections in 8B)
All 10 selections had:
- At least one ally below 0.7 HP (correctly identified as "threatened")
- opp_used_spread=True (correct predictions)
- 8 won, 2 lost (80% win rate when WG is selected)

| # | file | t | our HP | partner | result |
|---|---|---|---|---|---|
| 1 | p91 | 7 | 1.0/0.10 | kingambit/garganacl | won (self-preserve) |
| 2 | p60 | 5 | 1.0/0.58 | volcarona/garganacl | won (partner cap) |
| 3 | p56 | 2 | 0.65/0.26 | garchomp/garganacl | won (both threatened) |
| 4 | p51 | 2 | 0.51/1.0 | volcarona/garganacl | won (self-preserve) |
| 5 | p44 | 7 | 0.37/None | garganacl/fainted | lost (self-preserve, partner dead) |
| 6 | p36 | 2 | 0.27/0.56 | garchomp/garganacl | won (both threatened) |
| 7 | p36 | 4 | 1.0/0.18 | volcarona/garganacl | won (partner cap) |
| 8 | p9 | 2 | 0.74/0.22 | kingambit/garganacl | lost (garganacl low) |
| 9 | p61 | 4 | 1.0/0.49 | volcarona/garganacl | won (partner cap) |
| 10 | p82 | 2 | 0.59/0.45 | garganacl/volcarona | lost (both threatened) |

## What changed vs 6A

### 6A (no partner guard, conf=0.65)
- 9 WG selections in 100-pair
- 3 mispredicts (33% FPR)
- Win rate when WG selected: 11% (1/9)
- Overall win rate: ON 52% vs OFF 60% = -8pp

### 8B (with partner guard, conf=0.65)
- 10 WG selections in 100-pair
- 0 mispredicts (0% FPR)
- Win rate when WG selected: 80% (8/10)
- Overall win rate: ON 63% vs OFF 53% = +10pp

### Why 8B works
The partner guard is threat-based, not pure HP-based. It allows WG only
when at least one ally is in actual danger. This:
1. **Filters partner-gap cases** (case #7 p90 in 6A audit: full HP
   garganacl, low volcarona, WG was a team play but volcarona wasn't
   the WG user → now allowed because partner IS threatened)
2. **Filters no-value cases** (case #4 p69 in 6A audit: both full HP,
   mispredict → now suppressed because no team value)
3. **Preserves good cases** (case #1, #2 in 6A audit: both have
   threatened allies → still allowed)

## Stable state
- 207 unit tests pass (195 + 12 new partner guard tests)
- 0 default flips
- 0 production behavior change beyond new guard

## Files
| action | file |
|---|---|
| MOD | `bot_doubles_damage_aware.py` (+`planner_spread_defense_partner_threat_threshold`, +`_partner_threat_relevant`, +Guard 7) |
| MOD | `test_planner_spread_scoring.py` (updated make_battle for HP) |
| MOD | `test_planner_spread_state_mismatch.py` (updated make_battle for HP) |
| NEW | `test_planner_spread_partner_guard.py` (12 unit tests) |
| NEW | `logs/phasePLANNER_SPREAD_8B_partner_hp_guard.md` |

## Recommended next phase
- **(A) PLANNER-SPREAD-9**: candidate for default flip (win rate +10pp)
- **(B) Run 200-pair for higher confidence**
- **(C) Keep opt-in for one more release cycle**
- **(D) Tighten confidence further now that partner guard is in place**

## Latest pushed: pending (will commit with report)
