# Phase PLANNER-5 — MVP Track Closeout (No Implementation)

## 1. Summary

**PLANNER MVP track CLOSED** as
`ARCHITECTURE_READY / DATA_INSUFFICIENT_FOR_IMPLEMENTATION`.

This is a **docs-only closeout** (no
implementation). Per user decision:
- PLANNER-4 dry-run showed 0 flips
  (same as CONTROL-4B)
- Implementing +200 would be an opt-in
  no-op on top of existing CONTROL-4B
- Adding more opt-in no-ops adds code
  without behavior change
- Better to close with discipline than
  add duplicate code

**Status of PLANNER work**:
- PLANNER-1: architecture ready
- PLANNER-2: audit fields ready
- PLANNER-3: design ready
- PLANNER-4: dry-run formula verified,
  but 0 flips in existing data
- PLANNER-5: closed without implementation

**No scoring change. No default flip.
No new feature.**

## 2. Final PLANNER Track Status

| phase | decision | committed | pushed |
|---|---|---|---|
| PLANNER-1 | `ARCHITECTURE_READY` (with `AUDIT_GAP_FOUND`) | (in PLANNER-2 commit) | ✓ |
| PLANNER-2 | `AUDIT_GAP_FIXED` | (in PLANNER-2 commit) | ✓ |
| PLANNER-3 | `MVP_DESIGN_READY` | n/a (docs only) | n/a |
| PLANNER-4 | `INSUFFICIENT_DATA` (0 flips) | n/a (docs only) | n/a |
| **PLANNER-5** | **`ARCHITECTURE_READY / DATA_INSUFFICIENT_FOR_IMPLEMENTATION`** (this closeout) | (this commit) | (this push) |

## 3. Why Close Without Implementation

### 3.1 PLANNER-4 evidence

The dry-run tested 12 configurations
(4 future_value_scales × 3 confidence_floors)
across 3 data sources:
- SETUP-8 100-pair treatment (1879 turns)
- CONTROL-4A 5-pair probe (83 turns)
- ITEM-2 4-pair probe (63 turns)

**Result**: 0% flip rate, 0% over-flip rate
across all 36 configurations.

### 3.2 Why 0 flips

Two structural reasons:
1. **Trigger never fires**: existing
   artifacts have 0 opp stat-boost
   usage. Confidence = 0. Below any
   floor. Intent_value = 0.
2. **Status-move raw score = 0**:
   anti-setup moves have raw score 0
   in the audit. For the planner to
   flip, intent_value would need to
   exceed 200-500 (selected_score).
   But future_value is typically 50-150.
   Net: negative intent_value.

### 3.3 The trap

If we implement +200 anyway, it would
be a **fourth opt-in no-op** in a row
(SETUP-3A, SPREAD, CONTROL-4B, PLANNER-5).
The bot would have 4 conservative hooks
that never fire. Code bloat without
behavior change.

Per CONTROL-6 non-goals: "no broad setup
bonus revival". PLANNER-5 would violate
this spirit.

## 4. Future Reopen Conditions

PLANNER MVP may be **resumed** if **any**
of the following is true:

### 4.1 Curated scenario with forced setup

A 5-pair or 20-pair probe where the
opp's AI is forced to use setup moves
(e.g., Smeargle + SD lead, Whimsicott +
Encore). The current 5-pair probe in
CONTROL-4A used teams with setup users
but the AI didn't actually use them.

### 4.2 New data with opp setup revealed

A re-run of the 100-pair probe with:
- ITEM-2 capture enabled (so
  `opp_active_moves_revealed` is
  populated)
- A subset where opp actually uses
  SD/NP/CM/etc.

### 4.3 Status-move scoring redesign

The structural issue (status moves =
raw score 0) is the deeper problem.
A redesign that gives status moves a
baseline score of 30-50 would let the
planner add value on top. This is a
separate track (not MVP scope).

### 4.4 New visible trigger source

If a new visible-only signal is
identified (e.g., a poke-env event that
captures opp's intent to set up), the
confidence calculation could pick it
up. This is also a separate track.

## 5. What Remains Committed

The PLANNER-1+PLANNER-2 work is already
committed + pushed:
- `bot_doubles_intent_classifier.py`
  (NEW, pure function)
- `test_doubles_intent_classifier.py`
  (NEW, 33 tests)
- `doubles_decision_audit_logger.py`
  (M, +4 intent fields)
- `bot_doubles_damage_aware.py` (M, wire
  4 fields)

These 4 files are **observability only**
— no scoring change. They provide
4 new audit fields (selected_intent,
intent_candidates, rejected_intent_reasons,
intent_value_total) for any future
planner work to use.

The dry-run analyzer
(`analyze_intent_planner_dryrun.py`) is
also committed. It's a measurement
instrument, no production code.

## 6. What Was NOT Done (Correctly)

Per user decision:
- ❌ No PLANNER-5 implementation
- ❌ No +200 planner bonus
- ❌ No status-move scoring baseline change
- ❌ No confidence floor = 0
- ❌ No 100/200-pair
- ❌ No weather/terrain planner
- ❌ No Beat Up / Weakness Policy scoring
- ❌ No Mega/RL/V3d.1
- ❌ No `test_51` touched
- ❌ No commit to `learned_preview_v3d1`
- ❌ No V3d.1 PAUSE resumption
- ❌ No `logs/vgc2026_phaseV3d1_model.json`

## 7. Stable State

- 0 source files modified in this phase
- 0 default flips
- 0 commit/push yet (this doc will be the
  next commit)
- 0 `test_51` touched
- 0 `learned_preview_v3d1` promotion
- 0 V3d.1 PAUSE resumption
- 0 model artifacts

## 8. PLANNER vs CONTROL: Comparison

| aspect | CONTROL track | PLANNER track |
|---|---|---|
| Implementation | yes (CONTROL-4B) | no (closed) |
| Default state | OFF (opt-in) | n/a (no impl) |
| Result | safe but inert | n/a |
| Track philosophy | "ship a safe opt-in" | "don't ship another no-op" |
| Future resume path | CONTROL-5+ if data changes | PLANNER-5 reopen conditions above |

## 9. Decision

**`ARCHITECTURE_READY / DATA_INSUFFICIENT_FOR_IMPLEMENTATION`**.

The planner design is sound, but the
existing data does not exercise the
trigger. Implementing now would be a
no-op. The honest decision is to close
the MVP track with discipline.

## 10. Recommendations for the User

### 10.1 Pause feature work

After CONTROL-6 + PLANNER-5 closeouts,
the natural next step is to **pause
feature work** and consider:

- Report/dashboard cleanup
- Runner scenario tooling
- Endgame item/ability refinement (with
  concrete evidence)

### 10.2 Resume conditions for PLANNER

If the user wants to revisit PLANNER:

1. Build a 5-pair probe with **forced
   setup usage** (e.g., scripted AI
   that always uses SD on turn 1)
2. Re-run PLANNER-4 dry-run on this
   probe
3. If eligible > 0, implement with the
   chosen magnitude
4. Otherwise, redesign status-move
   scoring baseline (separate track)

## 11. Final PLANNER Track Timeline

```
2026-06-20  PLANNER-1  ARCHITECTURE_READY
2026-06-20  PLANNER-2  AUDIT_GAP_FIXED
                       (committed + pushed in 67c8b1f via PLANNER-2)
2026-06-20  PLANNER-3  MVP_DESIGN_READY (docs only)
2026-06-20  PLANNER-4  INSUFFICIENT_DATA (docs only)
2026-06-20  PLANNER-5  CLOSED — ARCHITECTURE_READY /
                       DATA_INSUFFICIENT_FOR_IMPLEMENTATION
                       (this closeout)
```

## 12. Stable State

- 0 source files modified in PLANNER-5
- 0 default flips
- 0 commit/push yet
- 0 `test_51` touched
- 0 `learned_preview_v3d1` promotion
- 0 V3d.1 PAUSE resumption
- 0 model artifacts

## 13. Do-Not-Do (Final)

- No scoring change (closeout only).
- No default flip (still OFF).
- No `test_51` touched.
- No commit/push before review.
- No 100/200-pair.
- No `learned_preview_v3d1` promotion.
- No V3d.1 PAUSE resumption.
- No `logs/vgc2026_phaseV3d1_model.json`.
- No PLANNER-5 implementation in this
  phase.
- No status-move scoring baseline change.
- No confidence floor = 0.
- No weather/terrain planner.
- No Beat Up / Weakness Policy scoring.
- No Mega/RL/V3d.1.
- No broad setup revival.
- No all-status-move bonus.

## 14. References

| source | path | role |
|---|---|---|
| PLANNER-ROADMAP-1 | `logs/phasePLANNERROADMAP1_doubles_intent_planner_architecture.md` | strategy |
| PLANNER-1 | `logs/phasePLANNER1_intent_planner_architecture_audit.md` | architecture |
| PLANNER-2 | `logs/phasePLANNER2_audit_gap_fix.md` | audit fields |
| PLANNER-3 | `logs/phasePLANNER3_anti_setup_mvp_design.md` | design |
| PLANNER-4 | `logs/phasePLANNER4_anti_setup_dryrun.md` | dry-run |
| PLANNER-4 (SETUP-8) | `logs/phasePLANNER4_SETUP8_treatment.md` | 100-pair results |
| PLANNER-4 (5-pair) | `logs/phasePLANNER4_CONTROL4A_5pair.md` | curated results |
| PLANNER-4 (ITEM-2) | `logs/phasePLANNER4_ITEM2_4pair.md` | post-ITEM-2 results |
| Classifier | `bot_doubles_intent_classifier.py` | NEW (committed) |
| Dry-run analyzer | `analyze_intent_planner_dryrun.py` | NEW (uncommitted) |
| CONTROL-6 | `logs/phaseCONTROL6_control_closeout.md` | similar closeout pattern |
| CONTROL-4B | `bot_doubles_damage_aware.py` (+297 lines) | existing safe opt-in |

## 15. Final Summary

- **Decision**: `ARCHITECTURE_READY /
  DATA_INSUFFICIENT_FOR_IMPLEMENTATION`.
- **Top 5 findings**:
  1. PLANNER-1..4 complete: architecture
     ready, audit fields ready, design
     ready, dry-run formula verified.
  2. PLANNER-4 dry-run: 0 flips across
     12 configs × 3 data sources.
  3. Trigger never fires: 0 opp setup
     usage in artifacts, confidence = 0,
     intent_value = 0.
  4. Structural: status-move raw = 0
     (anti-setup can't compete with
     damage).
  5. Implementing +200 would be a 4th
     opt-in no-op. Better to close with
     discipline.
- **Audit fields sufficient?** YES
  (PLANNER-2 added 4 fields, available
  for any future planner work).
- **Exact next recommended phase**:
  **pause feature work**. Resume
  conditions documented above.
- **No scoring change. No commit yet.
  No `test_51`. No
  `learned_preview_v3d1`. No V3d.1 PAUSE
  resumption.**
- **No `logs/vgc2026_phaseV3d1_model.json`.**
- **Default state**: still OFF (no
  PLANNER implementation).
- **Discipline > duplicate code.**
