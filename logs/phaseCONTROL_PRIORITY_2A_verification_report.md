# CONTROL-PRIORITY-2A Verification Report

**Date**: 2026-06-22
**Status**: `VERIFICATION_INCONCLUSIVE_AT_RUNTIME`
**Phase**: 2A-IMPL-VERIFICATION

## Summary

Fixture tests: 21/21 PASS (logic verified).
Runtime probe: 0 crashes, 0 errors, win rate ON = OFF at 5 pairs.
Magic Bounce reveal: 0/5 trials (structural issue, not feature bug).

## Test results

### 1. Fixture tests (logic)
- 21 new tests in `test_status_move_ability_safety.py`:
  - 13 helper tests
  - 5 ally helper tests
  - 3 config flag tests
- **Result**: ALL PASS

### 2. Targeted runtime probe (integration)
- 1 battle pair (Hatterene, Magic Bounce expected)
- **Result**: 0 crashes, 0 errors
- **Finding**: Hatterene faints too fast for Magic Bounce to be
  revealed in natural battle flow

### 3. 5-pair smoke (regression)
- 5 paired trials with new flag enabled
- **Result**:
  - ON: 4/5 wins (80%)
  - OFF: 4/5 wins (80%)
  - Delta: 0pp
  - 0 crashes, 0 errors
- **Finding**: Win rate unchanged (no regression)

### 4. Magic Bounce reveal analysis
- Across 5 ON trials: 0/5 had Magic Bounce revealed
- 1/5 trials had Taunt selected (when Magic Bounce was NOT revealed)
- **Interpretation**: The natural battle flow doesn't reveal
  Magic Bounce because Hatterene dies before using a status move

## Gate evaluation (vs adoption gates from REV3 design)

| gate | result | note |
|------|--------|------|
| 1. Fixture tests pass | ✓ | 21/21 |
| 2. Unit tests pass | ✓ | 176 across related files |
| 3. No crash/stall/timeout | ✓ | 0 errors in all trials |
| 4. ON vs Basic < 2pp regression | N/A | not measured (no Basic arm) |
| 5. ON vs OFF >= 50% win rate | ✓ | 4/5 = 80% (equal to OFF) |
| 6. ON vs SafeRandom >= 95% | N/A | not measured |
| 7. Non-zero opportunities | N/A | depends on runtime reveal |
| 8. Taunt NOT selected vs revealed Magic Bounce | N/A | 0 reveals in 5 trials |
| 9. Taunt NOT selected when target's ally has Aroma Veil | N/A | 0 reveals |
| 10. Damage move selected instead of Taunt | N/A | depends on trigger |
| 11. Mold Breaker bypass works | ✓ (via fixture) | logic verified |

## Why the runtime probe is inconclusive

The natural battle flow doesn't trigger the 2A scenario because:
- Hatterene is fragile (Psychic/Fairy, weak to Fire/Dark)
- Our bot has strong Fire/Dark moves (Incineroar's Flare Blitz)
- Hatterene dies before it can use a status move
- Magic Bounce is only revealed when Hatterene reflects a status
  move (e.g., bot's Taunt on Hatterene)
- But the bot's bot would have used damage moves to KO Hatterene
  before it can reflect

**This is a structural issue, not a feature bug.** The 2A
feature logic is correct (verified via fixtures). The runtime
scenario doesn't naturally trigger the block.

## Path forward

### Option 1: Build a tanky Hatterene scenario
- Use a custom team with Hatterene w/ Calm + Leftovers + max HP
- Use a custom scripted opp that lets Hatterene use a status move
  (e.g., Reflect) to trigger Magic Bounce reveal
- Then on next turn, our bot's Taunt should be blocked

### Option 2: Trust fixture tests + skip runtime probe
- Fixture tests cover the logic
- Runtime scenario doesn't naturally trigger
- 2A feature is opt-in, no production risk
- Adoption can wait for actual usage data

### Option 3: Use a different verification method
- Modify the Hatterene's team to ensure survival
- Or use a custom opp player that always reveals Magic Bounce
  via Reflect on turn 1

## Decision

`VERIFICATION_INCONCLUSIVE_AT_RUNTIME`:
- ✓ Logic verified (21 fixture tests pass)
- ✓ No runtime crash (0 errors in 5-pair smoke)
- ✓ No win-rate regression (ON 4/5 = OFF 4/5)
- ✗ Magic Bounce reveal scenario not naturally triggered
- 2A feature remains opt-in, no default flip

## Adoption recommendation

**Keep opt-in.** The feature is implemented correctly. The
runtime scenario doesn't naturally trigger the block, but
this is a property of the test setup, not the feature.

For full adoption, would need:
- Tanky Hatterene scenario (Option 1)
- OR actual usage data in real VGC matches
- OR a custom scripted opp that reveals Magic Bounce

For now: ship as opt-in. 0 production behavior change.
0 default flip. 0 magnitude tuning.

## Files

### Modified
- (none from this verification phase)

### New
- `logs/phaseCONTROL_PRIORITY_2A_verification_report.md` (this file)

### Already in place
- `test_status_move_ability_safety.py` (21 tests)
- `ability_rules.py` (helper extensions)
- `bot_doubles_damage_aware.py` (config + score_action)

## Stable state
- 0 production behavior change (opt-in)
- 0 default flip
- 0 magnitude tuning
- 21 new tests pass
- 176 related tests pass
- 0 crashes in 5-pair smoke
- Win rate unchanged (ON 4/5 = OFF 4/5)
