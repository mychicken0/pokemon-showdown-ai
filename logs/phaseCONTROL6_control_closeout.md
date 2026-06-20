# Phase CONTROL-6 — Control Track Closeout

## 1. Summary

**Closeout** of the CONTROL track. All
phases committed + pushed to origin. No
scoring change, no default flip, no
production behavior change.

**Status**: CONTROL-1..4B done. CONTROL-5+
**deferred** (see §6).

**Default state**: **OFF preserved**
across all CONTROL flags. No adoption.

## 2. CONTROL Track Timeline

| phase | title | decision | committed | pushed |
|---|---|---|---|---|
| CONTROL-1 | Unified Control Move Evidence Audit | `EVIDENCE_CLEAR_CONTROL_UNDERUSED` | `7cc40ba` | ✓ |
| CONTROL-2 | (skipped — audit fields sufficient) | n/a | n/a | n/a |
| CONTROL-3 | Anti-Setup Disruption Intent Design | `DESIGN_READY` (user decisions captured) | (in CONTROL-4B commit) | ✓ |
| CONTROL-4A | Anti-Setup Dry-Run + 5-Pair Probe | `INSUFFICIENT_DATA` for magnitude | (in CONTROL-4B commit) | ✓ |
| CONTROL-4B | Anti-Setup Implementation (opt-in) | `IMPLEMENTED_OPT_IN_SAFE` + `BONUS_INERT` | `67c8b1f` | ✓ |
| CONTROL-5+ | (deferred — see §6) | n/a | n/a | n/a |
| **CONTROL-6** | **Closeout docs (this file)** | **n/a** | (this commit) | (this push) |

## 3. Final Per-Phase Status

### CONTROL-1: Evidence Audit
- **Outcome**: Anti-setup family (Taunt /
  Encore / Disable / Quash) is NEVER
  selected across 1879 SETUP-8 turns
  (321 legal opportunities). Mean raw
  score -12.85 (negative).
- **Spread defense** (Wide Guard / Quick
  Guard): 35 legal, 0 selected, mean
  -12.86.
- **Comparison**: Bot values Tailwind
  (37.4% rate, mean 190), Fakeout
  (18.4%, mean 261), Pollen Puff
  (50%, mean 153), Detect (17.9%, mean
  57). The bot values some control
  moves but actively avoids anti-setup
  disruption.
- **Decision**: `EVIDENCE_CLEAR_CONTROL_UNDERUSED`.
- **Report**: `logs/phaseCONTROL1_control_move_evidence_audit.md`.
- **Per-arm reports**:
  `logs/phaseCONTROL1_SETUP8_full.md`,
  `logs/phaseCONTROL1_SETUP8_baseline.md`,
  `logs/phaseCONTROL1_ACCURACY3.md`.

### CONTROL-3: Design
- **Target moves**: Taunt, Encore,
  Disable, Quash (4 only).
- **Visible-only trigger**: per AGENTS.md,
  no species guessing, no meta lookup,
  no random-set inference.
- **Magnitude**: +200.0 (chosen by user;
  matches the conservative pattern).
- **Anti-spam**: cap 2 picks per game,
  min gap 3 turns.
- **Guards**: 6 (master switch, move
  allowlist, user survives, opp target,
  signal sum >= 1.0, anti-spam).
- **User decisions captured**:
  - Q1: Single magnitude (per-move
    tuning deferred)
  - Q2: Threshold 1, visible-only
  - Q3: Cap 2
  - Q4: No 100-pair in CONTROL-4
  - Q5: Default OFF confirmed
- **Report**:
  `logs/phaseCONTROL3_anti_setup_design.md`.

### CONTROL-4A: Dry-Run
- **Eligibility helper**:
  `bot_doubles_anti_setup_eligibility.py`
  (pure function, 51 tests pass).
- **Dry-run analyzer**:
  `analyze_anti_setup_dryrun.py` (sweep
  +100/+150/+200/+250/+300).
- **SETUP-8 100-pair treatment**: 0
  eligible (200-pair artifacts pre-date
  ITEM-2, opp-context counters 0).
- **ITEM-2 4-pair probe**: 0 eligible
  (curated teams don't include setup
  users in active slots).
- **5-pair targeted probe** (curated
  teams with BOTH anti-setup and
  stat-boost users): 0 eligible across
  83 turns. The AI never used stat-boost
  moves in any battle.
- **Decision**: `INSUFFICIENT_DATA` for
  magnitude. Conservative trigger
  design = safe but inert.
- **Report**:
  `logs/phaseCONTROL4A_anti_setup_dryrun.md`,
  `logs/phaseCONTROL4A_5pair_probe.md`.

### CONTROL-4B: Implementation
- **Bonus**: +200 to Taunt/Encore/
  Disable/Quash candidates.
- **Default state**: OFF (master switch
  `enable_anti_setup_disruption_intent`).
- **Eligibility**: 6 guards (master,
  move allowlist, user survives,
  opp target, signal sum >= 1.0,
  anti-spam).
- **Visible-only signal sources**:
  - `opponent_used_stat_boost_setup`
    counter (1.0)
  - `opponent_used_tailwind` (0.5) /
    trickroom (0.5)
  - Field TW/TR active (0.5 each)
  - Revealed stat-boost moves (ITEM-2,
    1.0)
  - Revealed high-BP moves
    (Disable only, 1.0)
- **Smoke**: 5-pair, 10/10 battles ok,
  0 errors. 0 anti-setup moves selected
  in 5-pair (conservative trigger).
- **Decision**: `IMPLEMENTED_OPT_IN_SAFE`
  + `BONUS_INERT`.
- **Test count**: 19 new tests + 51
  prior tests, all pass.
- **Report**:
  `logs/phaseCONTROL4B_implementation.md`.

## 4. Stable State (Verified)

### Defaults (all OFF or safe)

```python
enable_anti_setup_disruption_intent: bool = False
anti_setup_disruption_bonus: float = 200.0
anti_setup_disruption_max_picks_per_game: int = 2
anti_setup_disruption_min_turn_between_picks: int = 3
anti_setup_disruption_require_survival: bool = True
anti_setup_disruption_min_opp_setup_signal: float = 1.0
```

### Target moves (4 only)

```python
ANTI_SETUP_DISRUPTION_TARGETS = frozenset({
    "taunt", "encore", "disable", "quash",
})
```

### Tests
- 19 CONTROL-4B tests pass
- 51 CONTROL-4A tests pass
- 43 CONTROL-1 tests pass
- All committed + passing on main

## 5. Why CONTROL-5 Was Deferred

CONTROL-5 would extend the bonus to
spread defense (Wide Guard, Quick Guard,
Crafty Shield). Per user spec, it is
**deferred** for these reasons:

1. **SPREAD track already explored this**.
   The existing wide_guard_spread_pressure_bonus
   is a similar mechanism, and prior
   SPREAD-2..4 reports concluded the
   bonus is "inert" because the trigger
   (opp spread/priority observed) does
   not overlap with the spread-defense
   opportunity window.

2. **CONTROL-4B is already inert**. Adding
   another opt-in bonus that rarely
   fires would not address any visible
   pain point.

3. **No evidence of an actual problem**.
   CONTROL-1 found 35 spread-defense
   opportunities (Wide Guard / Quick
   Guard) with 0 selection and mean
   -12.86 — but the issue is the same
   structural one (status-move scoring
   returns 0.0), not a missing flag.

## 6. Future Work — Criteria for Resume

CONTROL-5+ may be resumed if **any** of
the following is true:

### 6.1 Better visible trigger data

If the audit logger is fixed or improved
to fire `opponent_used_*` counters
reliably across all 100-pair arms:

- Re-run CONTROL-4A with the fixed audit
- If eligible turns > 0, re-tune
  magnitude
- Then consider extending to spread
  defense

### 6.2 Curated scenario with forced setup

A scenario where the opp is forced to
use setup moves (e.g., Smeargle with
Swords Dance + high speed, Tailwind
lead) would let the trigger path fire:

- Build a curated pool with Smeargle or
  Whimsicott in lead
- Run 5-10 pairs
- Re-run CONTROL-4A

### 6.3 Status-move scoring redesign

The structural issue (status moves
return 0.0 if has-damaging-move) makes
ALL status moves uncompetitive. A
broader fix would change the scoring
formula (e.g., `0.7 * max_damage_score`
or `0.5 * mean_damage_score`):

- This is a design change, not an
  opt-in flag
- Would require its own qualification
  gate
- May benefit more than 1 family at
  once

## 7. Other Open Items (Out of CONTROL Track)

Per user spec, the next feature should
**not** be a support/control bonus.
Suggested candidates:

1. **Report/dashboard cleanup**:
   Consolidate track statuses into a
   single dashboard. Currently the
   status is scattered across
   `walkthrough.md`, `CURRENT_STATE.md`,
   and per-track log files.

2. **Runner scenario tooling**:
   Improve the curated probe workflow
   (currently requires manual file
   editing + manual `bot_vgc2026_phaseV3a2_reality.py`
   invocation). Could add a
   `run_curated.py` helper that reads
   pair_plan.json and runs all pairs.

3. **Endgame item/ability refinement**:
   Per ITEM-2, the audit fields are now
   populated. If a specific item/ability
   pain point is identified, it could be
   addressed as a CONTROL-style opt-in
   bonus (but only with concrete evidence
   first).

## 8. Decision

**`HEALTHY`** closeout.

- All CONTROL phases committed + pushed
- Default state preserved (OFF)
- No production behavior change
- No default adoption
- Future work requires better visible
  trigger data or curated scenario that
  actually uses setup/control moves

## 9. Do-Not-Do (Final)

- No scoring change (closeout only).
- No default flip.
- No `test_51` touched.
- No commit to `learned_preview_v3d1`.
- No V3d.1 PAUSE resumption.
- No `logs/vgc2026_phaseV3d1_model.json`.
- No related track changes (no SETUP/
  ACCURACY/TARGET/COUNTER/ITEM/etc).
- No CONTROL-5/6/7+ implementation
  (this is closeout, not new work).
- No broad status-move scoring change
  (out of scope).

## 10. References

| source | path | commit |
|---|---|---|
| CONTROL-1 audit | `analyze_control_move_evidence.py` | `7cc40ba` |
| CONTROL-1 tests | `test_analyze_control_move_evidence.py` | `7cc40ba` |
| CONTROL-1 report | `logs/phaseCONTROL1_control_move_evidence_audit.md` | (gitignored) |
| CONTROL-3 design | `logs/phaseCONTROL3_anti_setup_design.md` | (gitignored) |
| CONTROL-4A helper | `bot_doubles_anti_setup_eligibility.py` | `67c8b1f` |
| CONTROL-4A analyzer | `analyze_anti_setup_dryrun.py` | `67c8b1f` |
| CONTROL-4A tests | `test_doubles_anti_setup_eligibility.py` | `67c8b1f` |
| CONTROL-4A reports | `logs/phaseCONTROL4A_*.md` | (gitignored) |
| CONTROL-4B implementation | `bot_doubles_damage_aware.py` (+297 lines) | `67c8b1f` |
| CONTROL-4B CLI flag | `bot_vgc2026_phaseV3a2_reality.py` (+46 lines) | `67c8b1f` |
| CONTROL-4B tests | `test_doubles_anti_setup_disruption.py` | `67c8b1f` |
| CONTROL-4B report | `logs/phaseCONTROL4B_implementation.md` | (gitignored) |
| 5-pair curated teams | `data/curated_teams/control4a/` | `67c8b1f` |

## 11. Final Summary

- **Decision**: `HEALTHY` closeout.
- **All CONTROL phases committed + pushed**:
  - `7cc40ba` (CONTROL-1)
  - `67c8b1f` (CONTROL-3, 4A, 4B)
- **Default state preserved**: all
  CONTROL flags OFF.
- **No default adoption**: conservative
  trigger design = bonus rarely fires.
- **Future work**: requires better
  visible trigger data or curated
  scenario that actually uses setup/
  control moves.
- **Recommended next feature** (per user):
  one of (1) report/dashboard cleanup,
  (2) runner scenario tooling, or
  (3) endgame item/ability refinement.
- **No scoring change. No commit to
  `learned_preview_v3d1`. No V3d.1 PAUSE
  resumption.**
- **No `logs/vgc2026_phaseV3d1_model.json`.**
