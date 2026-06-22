# CONTROL-PRIORITY-2A — Status-Move Ability Safety Implementation

**Date**: 2026-06-22
**Status**: `IMPLEMENTED` (opt-in, default OFF, no default flip)
**Phase**: 2A-IMPL

## Summary

Implemented the REV3 design for status-move ability safety.
The bot now has opt-in tracking for:
- Magic Bounce (target reflects status)
- Good as Gold (target immune to status)
- Aroma Veil (target blocks Taunt/Encore/Disable)
- Aroma Veil (target's ally blocks via ally protection)
- Mold Breaker / Teravolt / Turboblaze (attacker bypasses)

Default OFF (`enable_status_move_ability_safety = False`).
No default flip. No production behavior change.

## Files modified

### `ability_rules.py`

1. `should_avoid_status_into_ability(target, move, attacker=None)`:
   - Added `attacker=None` parameter (backward compatible)
   - Added Mold Breaker / Teravolt / Turboblaze bypass check
   - Added Aroma Veil case (only for Taunt/Encore/Disable)
   - Fixed existing bug (Mold Breaker was not checked)

2. New `ally_has_aroma_veil(target, battle)`:
   - Returns True if target's active partner has revealed Aroma Veil
   - Used to detect ally-side protection

### `bot_doubles_damage_aware.py`

1. Added 5 config fields in `DoublesDamageAwareConfig`:
   - `enable_status_move_ability_safety: bool = False` (default OFF)
   - `status_ability_safety_track_magic_bounce: bool = True`
   - `status_ability_safety_track_good_as_gold: bool = True`
   - `status_ability_safety_track_aroma_veil: bool = True`
   - `status_ability_safety_track_aroma_veil_ally: bool = True`

2. Modified `score_action` (around line 6477):
   - Inserted new 2A logic BEFORE the existing
     `enable_ability_awareness` block
   - Independent of `enable_ability_awareness` (per AGENTS.md)
   - Uses `should_avoid_status_into_ability` with attacker param
   - Uses `ally_has_aroma_veil` for ally-side check
   - Sub-flags filter which abilities are tracked
   - Returns 0.0 (or -100.0 if no damage alternative) when blocked
   - Increments `ability_blocks_avoided_by_battle` counter

3. Updated existing call site (line 6572, spread case):
   - Now passes `attacker=active_mon` to the helper

## Files added

### `test_status_move_ability_safety.py`

21 fixture tests covering:
- **TestShouldAvoidStatusIntoAbility** (13 tests):
  - Magic Bounce, Good as Gold, Aroma Veil blocks Taunt
  - Aroma Veil blocks Encore, Disable (specific moves)
  - Aroma Veil does NOT block Thunder Wave (out of scope)
  - Taunt allowed when ability not revealed
  - Damaging move NOT blocked vs Magic Bounce / Aroma Veil
  - Mold Breaker bypasses Magic Bounce
  - Teravolt bypasses Good as Gold
  - Turboblaze bypasses Aroma Veil
  - No attacker means no bypass check (backward compat)

- **TestAllyHasAromaVeil** (5 tests):
  - Ally has Aroma Veil → True
  - Ally has different ability → False
  - Ally fainted → False
  - No ally → False
  - Target itself has Aroma Veil → False (only partner)

- **TestConfigFlags** (3 tests):
  - Default OFF
  - Sub-flags default True
  - Flags can be modified

## Test results

- 21 new tests in `test_status_move_ability_safety.py`: ALL PASS
- 176 tests across related files: ALL PASS
- 0 regressions in existing tests
- `test_51` not touched (doesn't exist as separate file)
- No default flip
- No magnitude tuning

## Adoption status

**Status**: `IMPLEMENTED` (opt-in)
**Adoption**: NOT YET — feature is opt-in only.

To use the feature, set:
```python
config.enable_status_move_ability_safety = True
# Optional: disable specific sub-flags
config.status_ability_safety_track_magic_bounce = False
```

## What 2A does NOT do (per spec)

- No magnitude tuning (anti_trick_room_response_bonus unchanged)
- No default flip (enable_status_move_ability_safety = False)
- No inference from species (revealed-only)
- No Aroma Veil on our side (out of scope)
- No Prankster priority interaction (out of scope)
- No Type immunity to status (out of scope)

## Path to adoption (deferred)

Per AGENTS.md adoption gates:
1. ✓ All tests pass (176)
2. ✓ No crash, stall, timeout
3. ⏳ ON vs Basic regression: not measured (opt-in, no run yet)
4. ⏳ ON vs OFF >= 50% win rate: not measured
5. ⏳ ON vs SafeRandom >= 95%: not measured
6. ⏳ Taunt not selected vs revealed Magic Bounce / Good as Gold / Aroma Veil
7. ⏳ Taunt not selected when target's ally has Aroma Veil
8. ⏳ Damage move selected instead of Taunt in these scenarios
9. ⏳ Attacker with Mold Breaker can still use Taunt (bypass works)

**Next phase**: 2A-IMPL-VERIFICATION (targeted probe + smoke + 20-pair preview)
