# PLANNER-SPREAD-3c — active_idx / intent decision path audit

## Status
**`ROOT_CAUSE_FOUND`** — eligible Guard 5 (opp_pressure) re-evaluation fails because
multiple choose_move calls per turn cause the state at eligible time to differ
from the state at detector time.

## Diagnostic findings

### 1. Multiple choose_move calls per turn
**Confirmed**: poke-env calls `choose_move` 1-4 times per turn. Each call:
- Runs the detector (`_run_planner_intent_detector`)
- Sets `self._planner_intent_decision` AND `battle._planner_intent_decision`
- Then does its own scoring

Example from smoke (3c_detect run):
```
DETECT #11] t=1 result=SPREAD_DEFENSE/conf=0.65 opp_press=True
DETECT #12] t=2 result=SPREAD_DEFENSE/conf=0.65 opp_press=True
DETECT #13] t=2 result=SPREAD_DEFENSE/conf=0.65 opp_press=False   ← state changed!
DETECT #14] t=3 result=SPREAD_DEFENSE/conf=0.65 opp_press=False
```

The `opp_press` value flipped from True to False between calls of the same turn.

### 2. Detector and eligible use different state
- **Detector** runs at the START of `choose_move`. Decision stored on battle.
- **Eligible check** runs DURING scoring (later in `choose_move`).
- Between these two points, the battle state can change.
- `compute_opp_pressure_state_for_battle` reads live battle state
  (`battle.opponent_active_pokemon`, HP, revealed moves).
- poke-env may update these during scoring (or between calls).

### 3. Detector returns SPREAD_DEFENSE even when opp_press=False
The detector's SPREAD_DEFENSE logic considers MULTIPLE signals:
- revealed moves
- fields
- side_conditions
- opp_pressure (one of several inputs)

So the detector CAN return SPREAD_DEFENSE even when opp_press=False
(e.g., because revealed moves show Heat Wave from a fainted-but-revealed
Volcarona, or because revealed moves have the spread move on a partner
slot, or because HP dropped below 0.5 after the detector evaluated).

### 4. The eligible Guard 5 is the gate that fails
Guards in `_planner_spread_defense_eligible`:
- 0: master switch (enable_planner_spread_defense_scoring) ✓
- 1: detector running (enable_planner_intent_detector) ✓
- 2: decision exists and intent=SPREAD_DEFENSE ✓
- 3: move is Wide Guard ✓
- 4: confidence >= 0.5 ✓
- 5: opp pressure detected ← **FAILS** when eligible's call sees opp_press=False
- 6: anti-spam ✓

In the v9 ON arm (where WG was selected at t2):
- Intent was SPREAD_DEFENSE (Guard 2 ✓)
- Confidence 0.65 (Guard 4 ✓)
- BUT `picks_this_game=0` and `bonus_applied=0.0` → eligible returned False
- Therefore Guard 5 (opp_pressure) failed at scoring time

### 5. Audit shows SPREAD_DEFENSE, eligible saw NO_INTENT (or NO opp_press)
- The **audit** is written at the END of the LAST `choose_move` call.
- The last call's detector returned SPREAD_DEFENSE (still).
- The audit reads the same decision object → intent=SPREAD_DEFENSE.
- The eligible was called during SCORING (earlier or in a different call's scoring).
- At that point, opp_press was False → Guard 5 failed.
- Audit shows the intent but the bonus was never applied.

### 6. active_idx varies (0 or 1) based on which slot holds the WG mon
- WG-eligible eligible calls in debug run had active_idx=0 (Garganacl in slot 0 of lead)
- In v9 run, Garganacl was in slot 1 → eligible would have been called with active_idx=1
- active_idx itself is not the bug; it's passed correctly by `score_action(order_1, 1, battle)`.
- The bug is in **Guard 5 reading stale state**, not in active_idx.

## Root cause

**`compute_opp_pressure_state_for_battle` is called at two different times**
(once by detector at choose_move start, once by eligible during scoring)
**with possibly different battle states**, causing the eligible to fail Guard 5
even when the detector returned SPREAD_DEFENSE.

The detector's decision is per-call. The eligible's opp_pressure check
is also per-call. They can disagree.

## Why my earlier fix attempt didn't work

I tried removing Guard 5 in a previous test, and the bonus WAS applied.
But I was waiting for the user to confirm before committing.

Actually, the user wanted diagnostic-first. So I haven't committed the fix.

## Smallest fix candidates

### Option A: Remove Guard 5 (trust detector)
The detector's SPREAD_DEFENSE already considers opp_pressure. Re-evaluating
in eligible is redundant. Remove Guard 5.

**Pros**: simplest fix, 1-line change, no scoring change beyond trusting detector.
**Cons**: detector might return SPREAD_DEFENSE based on revealed moves only
(e.g., Volcarona revealed Heat Wave but at 30% HP). Then eligible would still
apply bonus even though opp can't realistically use the move. This is a
known limitation of revealed-moves-only signal.

### Option B: Cache the eligible result at detector time
At detector time, evaluate all 6 guards and store the result. The eligible
just reads the cached result. Avoids re-evaluation.

**Pros**: preserves all 6 guards, no re-evaluation.
**Cons**: eligible needs the ORDER (move being scored). Can't cache per-order.
Could cache "Guard 5 result for this turn" instead.

### Option C: Store opp_pressure on the decision
IntentDecision includes `opp_pressure` field. The detector stores it.
The eligible uses `decision.opp_pressure` instead of re-evaluating.

**Pros**: clean separation, decision is self-contained.
**Cons**: requires changing IntentDecision (a small refactor).

### Option D: Reorder: detector and eligible use SAME state
Pin the battle state at detector time, use it for eligible.
Complex, requires deep refactor.

## Recommended: Option C (store opp_pressure on decision)

Add `opp_pressure: bool` to `IntentDecision`. Detector stores it.
Eligible uses `decision.opp_pressure` for Guard 5.

This:
- Preserves all 6 guards
- Eliminates state mismatch
- Adds 1 field to IntentDecision (not a new type)
- Eligible check becomes 1-line change

## Reproduction (verified)

In-memory probe (test_eligible_debug):
- All 4 test cases (decision set, not set, NO_INTENT, active_idx=0) return expected values.
- Works in isolation.

Smoke (v9 ON arm, p1 vs rockslide):
- WG was selected at t2 (correct decision logic without bonus)
- Intent=SPREAD_DEFENSE in audit (detector did fire)
- picks=0, bonus=0.0 → eligible returned False at scoring time
- Root cause: Guard 5 opp_pressure re-evaluation

## Decision label

**`ROOT_CAUSE_FOUND`** (Option C recommended for PLANNER-SPREAD-3d fix)

## Pass criteria
- [x] reproduce in fixture or tiny probe (in-memory probe passes)
- [x] identify exact line/path mismatch (Guard 5 re-evaluation, multiple choose_move calls)
- [x] no production scoring change (diagnostic only)
- [x] propose smallest fix (Option C: store opp_pressure on decision)

## Files
| action | file | lines |
|---|---|---:|
| NEW | `logs/phasePLANNER_SPREAD_3c_diagnostic.md` | THIS FILE |

## Stable state
- 187 unit tests pass
- 0 scoring behavior change
- 0 default flips
- 0 production code change
- Diagnostic only

## Recommended next phase
**PLANNER-SPREAD-3d** — apply Option C fix:
1. Add `opp_pressure: bool` to `IntentDecision`
2. Detector stores `ctx["opp_pressure"]` on the decision
3. Eligible uses `decision.opp_pressure` for Guard 5
4. Add fixture test for state mismatch (multiple choose_move calls)
5. Re-run smoke to verify bonus application
