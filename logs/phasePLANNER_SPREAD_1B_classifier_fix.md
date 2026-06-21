# PLANNER-SPREAD-1B — Classifier Fix Report

## Status
**`IMPLEMENTED_CLASSIFIER_FIXED`** — 14 false-positive moves removed from `SPREAD_MOVES`. 36 new fixture tests added. 168/168 tests pass.

## Goal
Fix the SPREAD_MOVES allowlist by removing 14 moves that are NOT actually spread in showdown (verified against `data/moves.ts`).

## False positives removed (14)

| move | showdown target | reason |
|---|---|---|
| waterpulse | any | single-target, 5 false fires in 20-pair smoke |
| alluringvoice | normal | single-target |
| drainingkiss | normal | single-target |
| heatcrash | normal | single-target (weight-based) |
| infernalparade | normal | single-target |
| luminacrash | normal | single-target |
| mudshot | normal | single-target |
| mudslap | normal | single-target |
| mysticalfire | normal | single-target |
| powergem | normal | single-target |
| ruination | normal | single-target |
| syrupbomb | normal | single-target (with side-effect) |
| temperflare | normal | single-target |
| thundercage | normal | single-target |
| torchsong | normal | single-target (boost self, was in STAT_BOOST_MOVES too) |

## True spread moves (kept, 18)

Per showdown's `data/moves.ts` (target = "allAdjacent" or "allAdjacentFoes"):

heatwave, rockslide, earthquake, dazzlinggleam, surf, eruption, discharge, sludgewave, boomburst, makeitrain, snarl, glaciate, muddywater, bleakwindstorm, sandsearstorm, wildboltstorm, springtidestorm, matchagotcha

## Test coverage

### New file: `test_planner_spread_moves_fix.py` (36 tests)

- **18 tests**: each true spread move (one per move)
- **15 tests**: each false positive (waterpulse, alluringvoice, etc.)
- **3 tests**: allowlist count, no false positives in allowlist, all true spreads in allowlist

### Test-first workflow
1. Wrote tests BEFORE the fix
2. Confirmed 17 tests fail (15 false-positive tests + 2 allowlist tests)
3. Applied fix to `SPREAD_MOVES`
4. Fixed `test_torchsong_no_spread_defense` to expect ANY non-SPREAD_DEFENSE intent (since torchsong fires ANTI_STAT_BOOST)
5. Fixed `test_allowlist_count` to expect 18 (was 19)
6. All 36 tests pass

### Final test counts
| suite | tests | status |
|---|---|---|
| test_planner_spread_moves_fix | 36 | ✓ (new) |
| test_bot_vgc2026_scripted_opp | 17 | ✓ |
| test_scenario_probe | 67 | ✓ |
| test_doubles_intent_classifier | 33 | ✓ |
| test_planner_intent_detector | 15 | ✓ |
| **Total** | **168** | **✓** |

## Impact

### Before fix
- 23 SPREAD_DEFENSE fires in 20-pair smoke
- 5 false positives (waterpulse × 5)
- Accuracy: 78% (18/23 real)

### After fix
- Same 23 fires would now produce 18 real fires + 5 NO_INTENT instead
- Expected accuracy: 100% (18/18 real, no false positives)
- New: 5 turns previously firing SPREAD_DEFENSE would now correctly fire NO_INTENT

### Stale artifacts warning
The 20-pair smoke artifacts in `logs/vgc2026_phasePLANNER_DATA_4_*_treatment_audit.jsonl` were generated with the OLD classifier (before this fix). They contain 5 false-positive SPREAD_DEFENSE fires. These should NOT be re-interpreted; the fix is for FUTURE runs.

## Stable state (per AGENTS.md)

- 168 unit tests pass
- 0 scoring change
- 0 default flips
- 0 `test_51` touched
- 0 audit logger changes
- 0 model artifacts
- 0 V3d.1 / RL / Phase 7
- 0 new battles
- 0 implementation
- Default OFF preserved (no scoring change)

## Files

| action | file | lines |
|---|---|---:|
| MOD | `bot_doubles_intent_classifier.py` | SPREAD_MOVES reduced from 33 to 18 moves |
| NEW | `test_planner_spread_moves_fix.py` | +310 (36 fixture tests) |

## Decision label

**`IMPLEMENTED_CLASSIFIER_FIXED`**

## Next step

**PLANNER-SPREAD-2: Narrow Spread Defense Scoring Implementation**
- Add `enable_planner_spread_defense_scoring: bool = False` config flag
- Add `planner_spread_defense_wg_bonus: float = 150.0` (small bonus)
- Implement per-slot additive Wide Guard boost when SPREAD_DEFENSE intent fires
- Add audit fields (observational)
- Default OFF (no behavior change unless flag ON)
- Adoption gates per PLANNER-IMPL-1: fixture → targeted probe → smoke → full benchmark
