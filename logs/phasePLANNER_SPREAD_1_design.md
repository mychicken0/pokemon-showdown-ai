# PLANNER-SPREAD-1 — Narrow Spread Defense Scoring Design

## Status
**`NEEDS_CLASSIFIER_FIX`** — The SPREAD_MOVES allowlist contains 14 of 33 moves that are NOT actually spread in showdown. Critical false positive: `waterpulse` (target="any", not spread) accounts for 5/23 (22%) of SPREAD_DEFENSE fires. Must fix the classifier before any scoring design.

## Goal
Design a narrow spread defense scoring integration. Reuse existing per-move policies. Default OFF. No scoring change yet.

## User's questions answered

### Q1: In 23 positives, was Wide Guard legal?
- **WG legal in at least one slot: 2/23 (8.7%)**
- After removing waterpulse: 2/18 (11.1%)

### Q2: If no WG, was Protect legal?
- **Protect legal in at least one slot: 19/23 (82.6%)**
- After removing waterpulse: 14/18 (77.8%)

### Q3: What was the selected action?
- `move protect` (slot 1, on 9 fires)
- `switch ..., pass` (3 fires)
- `pass, move protect` (2 fires)
- `move ..., move feint` (1 fire)
- `move ..., move heatwave` (1 fire)
- 0 fires chose Wide Guard (even when legal)

### Q4: Damage-prevention estimate?
- Not in the codebase yet. Would need a damage calculator (the bot has one but it's internal).
- For design: defer. Narrow scoring should ONLY boost WG when the spread threat is real and WG is legal.

### Q5: Which trigger moves are actually spread?

I verified each `SPREAD_MOVES` entry against showdown's `data/moves.ts`:

| Move | Showdown target | Is spread? |
|---|---|---|
| heatwave | allAdjacentFoes | YES |
| dazzlinggleam | allAdjacentFoes | YES |
| earthquake | allAdjacent | YES |
| rockslide | allAdjacentFoes | YES |
| **waterpulse** | **any** | **NO FALSE POSITIVE** |
| alluringvoice | normal | NO |
| drainingkiss | normal | NO |
| heatcrash | normal | NO |
| infernalparade | normal | NO |
| luminacrash | normal | NO |
| mudshot | normal | NO |
| mudslap | normal | NO |
| mysticalfire | normal | NO |
| powergem | normal | NO |
| ruination | normal | NO |
| syrupbomb | normal | NO |
| temperflare | normal | NO |
| thundercage | normal | NO |
| torchsong | normal | NO |
| bleakwindstorm | allAdjacentFoes | YES |
| boomburst | allAdjacent | YES |
| discharge | allAdjacent | YES |
| eruption | allAdjacentFoes | YES |
| glaciate | allAdjacentFoes | YES |
| makeitrain | allAdjacentFoes | YES |
| matchagotcha | allAdjacentFoes | YES |
| muddywater | allAdjacentFoes | YES |
| sandsearstorm | allAdjacentFoes | YES |
| sludgewave | allAdjacent | YES |
| snarl | allAdjacentFoes | YES |
| springtidestorm | allAdjacentFoes | YES |
| surf | allAdjacent | YES |
| wildboltstorm | allAdjacentFoes | YES |

**14 of 33 SPREAD_MOVES are NOT actually spread.** True spread moves: 19.

### Q6: What should scoring boost?
- Wide Guard is the only true spread-counter move
- Protect can be a fallback if WG unavailable (but weaker, single-slot)
- Switch is out of scope
- Recommendation: **boost only Wide Guard first**, not Protect

### Q7: Do-not-boost rules
- No WG legal
- Both allies immune/airborne (e.g., both Levitate for Earthquake)
- Spread move not actually hitting both targets
- Obvious KO available (one-shot counter to the spread user)

## False positive analysis

### waterpulse impact
- 5 of 23 SPREAD_DEFENSE fires (22%) are waterpulse false positives
- These should NOT fire SPREAD_DEFENSE (waterpulse is single-target)
- Removing them: 18 real SPREAD_DEFENSE fires (still significant)
- Without the fix, **any scoring design would over-fire by 22%**

### Other false positives in the 20-pair smoke
- 0 of 5 other false-positive moves (alluringvoice, drainingkiss, etc.) fired in this batch
- But they could fire in future batches if the team composition changes
- **All 14 false-positive moves need to be removed from SPREAD_MOVES**

## Proposed design (deferred until classifier fix)

### Scoring rules (post-fix)
1. **Trigger**: SPREAD_DEFENSE intent fires (after classifier fix)
2. **Boost**: only Wide Guard on slot 0 or slot 1
3. **Bonus magnitude**: small (e.g., +150.0, lower than `wide_guard_spread_pressure_bonus=500.0`)
4. **Do NOT boost**:
   - Protect (single-slot only, weaker than WG)
   - Switch (out of scope)
   - When WG is not legal in either slot
   - When opp pressure is not credible
5. **Reuse existing flag**: `enable_spread_defense_bonus=True` (no new config)

### Configuration
```python
class DoublesDamageAwareConfig:
    # PLANNER-SPREAD-1: opt-in narrow spread defense scoring.
    # Default OFF. Requires classifier fix (waterpulse etc).
    enable_planner_spread_defense_scoring: bool = False
    planner_spread_defense_wg_bonus: float = 150.0
```

### Integration
- Add `_apply_planner_spread_defense_bonus` to `choose_move`
- Called AFTER `slot_0_scores` and `slot_1_scores` are computed
- Called BEFORE `_compute_joint_scores`
- Per-slot additive bonus (same as existing patterns)

### Adoption gates
1. Static/unit tests
2. Fixture tests (battle with heatwave revealed, verify WG boost)
3. Targeted probe (1 battle, flag ON)
4. Smoke (5-20 pairs, OFF vs ON)
5. Full benchmark (100 pairs, no regression > 2pp)
6. Adoption (all gates + user approval)

## Do-not-implement checklist (per user)

- [x] Design-only, no scoring change
- [x] No default flip
- [x] No battle run
- [x] Use PLANNER-DATA-4 positives (23 fires analyzed)
- [x] Boost only Wide Guard first, not Protect
- [x] Bonus small/capped (150.0)
- [x] Require WG legal and spread threat credible
- [x] No Earthquake boost unless grounded logic available
- [x] No Protect boost (defer to IMPL-2 if needed)
- [x] No switch boost (out of scope)
- [x] **Classifier fix required FIRST** (waterpulse + 13 others)

## Files
- Files inspected: `bot_doubles_intent_classifier.py`, `bot_doubles_damage_aware.py`, `data/moves.ts`, `logs/vgc2026_phasePLANNER_DATA_4_on_*.jsonl`
- Files modified: NONE (design only)

## Stable state
- 132 unit tests pass
- 0 scoring change
- 0 default flips
- 0 audit logger changes
- 0 model artifacts
- 0 V3d.1 / RL / Phase 7
- 0 new battles
- 0 implementation

## Decision label
**`NEEDS_CLASSIFIER_FIX`**

## Next steps

1. **PLANNER-SPREAD-1B: Classifier fix** (must do first)
   - Remove 14 false-positive moves from `SPREAD_MOVES`
   - Add fixture test verifying the fix
   - Re-run 20-pair smoke to confirm cleaner results
2. **PLANNER-SPREAD-2: Narrow scoring design** (after fix)
3. **OR pause and reconsider** if user prefers to keep detector as audit tool only

### Alternative: skip scoring
- Detector is observably stable as audit tool
- 23 fires (18 real) is informative but not enough for robust scoring
- The 100-positive threshold for "stronger implementation" is far away
- Status quo (audit tool only) is acceptable
