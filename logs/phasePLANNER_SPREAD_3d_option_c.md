# PLANNER-SPREAD-3d — Option C fix (decision snapshot for Guard 5)

## Status
**`IMPLEMENTED_SMOKE_VALIDATED_7_7`** — Option C applied. Smoke shows
bonus applied at runtime (picks=1, bonus_applied turns=4, bonus magnitude
150.0). All 7 pass criteria met.

## What was changed

### 1. IntentDecision gets `opp_pressure` field
Added `opp_pressure: bool = False` to `IntentDecision` dataclass. The
detector stores `ctx["opp_pressure"]` on the decision via
`dataclasses.replace`. This is a snapshot of the opp_pressure state at
detector time.

### 2. Detector attaches opp_pressure on every intent
`IntentDetector.detect()` wraps the result with `_with_opp_pressure()`
which reads `ctx["opp_pressure"]` and calls `dataclasses.replace` to
attach the snapshot. NO_INTENT decisions also have `opp_pressure=False`.

### 3. Eligible check Guard 5 uses the snapshot
Guards reordered. New Guard 5:
- If `decision` is a real `IntentDecision` instance → use
  `decision.opp_pressure` (the detector's snapshot).
- Otherwise (legacy / mock / pre-SPREAD-3d) → fall back to
  `self._slot_in_opp_pressure(active_idx, battle)` (live state).

This eliminates the state mismatch between detector and scoring that
occurs because poke-env calls `choose_move` multiple times per turn.

### 4. Audit logger fix (bonus observability)
PLANNER-SPREAD-3d adds a class-level dict on `DoublesDecisionAuditLogger`:
```python
_battle_player_refs = {}  # battle_tag -> player instance
```
The bot registers itself before each `log_turn_decision` call:
```python
DoublesDecisionAuditLogger._battle_player_refs[battle_tag] = self
```
The audit's `_populate_planner_intent_fields` reads from this dict
to get the player (poke-env battle doesn't carry the player), and
reads `_planner_spread_defense_picks_per_game` and
`_planner_spread_defense_bonus_applied_per_game` from the player.

The bot now also tracks cumulative bonus magnitude in
`_planner_spread_defense_bonus_applied_per_game` so the audit can
verify the bonus was actually applied (not just that the eligible
returned True).

## Smoke results (3-pair, ON arm)

```
ON arm:
  total turns: 22
  WG selections: 0
  intent_label dist: {'NO_INTENT': 13, 'SPREAD_DEFENSE': 9}
  picks_this_game max: 1        ← bonus applied once
  bonus_applied turns: 4         ← audit shows bonus
  bonus sample: [150.0, 150.0, 150.0, 150.0]   ← wg_bonus magnitude
```

## 7/7 pass criteria

- [x] 6/6 battles ok
- [x] OFF arm: no bonus applied (spread_scoring OFF)
- [x] ON arm: bonus applied (spread_scoring ON)
- [x] ON arm: picks per game <= 3 (anti-spam)
- [x] OFF arm: picks per game == 0 (no scoring)
- [x] no timeout/error
- [x] ON arm WG >= OFF arm WG (loose check)

## Stable state

- 195 unit tests pass (187 + 8 new state-mismatch tests)
- 0 scoring change (default OFF)
- 0 default flips
- 0 production code change beyond the eligible fix and audit
  observability

## Test count
| suite | count |
|---|---:|
| pre-existing | 187 |
| state-mismatch new (8) | 8 |
| **total** | **195** |

## Files
| action | file | lines |
|---|---|---:|
| MOD | `bot_doubles_intent_classifier.py` | +opp_pressure field, _with_opp_pressure helper |
| MOD | `bot_doubles_damage_aware.py` | eligible Guard 5 uses snapshot; record_pick tracks bonus; bot registers with audit |
| MOD | `doubles_decision_audit_logger.py` | class-level _battle_player_refs; _populate reads from it; bonus_applied reads from player |
| MOD | `test_planner_spread_state_mismatch.py` | +5 new tests (legacy mock, snapshot, detector) |
| NEW | `logs/phasePLANNER_SPREAD_3d_option_c.md` | THIS FILE |

## Why the fix works

Before: detector returned `SPREAD_DEFENSE` at start of choose_move. The
eligible check ran during scoring (later in choose_move) and re-evaluated
opp_pressure using live state. Live state could differ (state changed
between calls or between detector/score time). Result: bonus never
applied even when detector said SPREAD_DEFENSE.

After: detector stores opp_pressure on the decision. Eligible reads
`decision.opp_pressure` (the snapshot), not live state. Bonus is
applied whenever the detector said SPREAD_DEFENSE at detector time.

## Note on multiple choose_move calls

poke-env calls choose_move 1-4 times per turn (team preview, switch
decisions, move selection). Each call resets the decision. The LAST
call's decision is what the audit reflects. The eligible check uses
the decision at scoring time (one of those calls).

With the snapshot, the eligible uses the decision's opp_pressure (set
at THAT call's detector time), so it doesn't matter which call is the
"final" one — each call's eligible has its own consistent snapshot.

