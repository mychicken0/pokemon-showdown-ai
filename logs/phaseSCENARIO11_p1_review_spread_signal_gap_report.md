# Phase SCENARIO-11 — P1 Review + Spread Signal Gap Decision

## 1. Summary

SCENARIO-11 is a docs/audit-only phase.
It reviews the SCENARIO-10 Heat Wave
result, audits the spread signal gap
in the audit logger, and decides on
the canonical signal policy for
scripted scenarios.

**Decisions**:

- **P1_HEATWAVE_READY** (P1 is NOT
  blocked — Heat Wave scenario passes
  via canonical signal).
- **SPREAD_SIGNAL_GAP_NEEDS_FIX** (the
  bot's audit's `opponent_actions`
  field is `None` for scripted
  scenarios; needs audit logger fix
  OR validator policy).
- **NOT P1_BLOCKED** (we have a
  working canonical signal via the
  baseline audit's `scripted_actions`).

**Recommended policy**: **Option C**
(validator uses baseline
`scripted_actions` as canonical,
cross-checks bot's audit
`opponent_actions` if available,
marks `bot_opp_action_gap=True` if
disagreement).

**No new code, no new scenario, no
battle run, no commit/push until
user approval**.

## 2. P1 Heat Wave result review

### 2.1 SCENARIO-10 evidence recap

| battle | baseline scripted_actions | failures | scenario_id |
|---|---|---|---|
| 97255 | (1, 0, heatwave), (1, 1, protect) | 0 | spread_def_heat_wave |
| 97256 | (1, 0, heatwave), (1, 1, protect) | 0 | spread_def_heat_wave |

| treatment audit_turns | WG legal turns | opp_actions |
|---|---|---|
| 7 turns | 3, 4, 5 (slot 1) | None (all turns) |

All 7 pass criteria met via the
canonical signal (baseline
`scripted_actions`).

### 2.2 Framework gap confirmed

The bot's audit's
`opponent_actions` field is `None` for
all turns in the SCENARIO-10 audit
(and for all P0 audits: anti_tr,
anti_tw, anti_stat_boost).

Cross-check across all 4 P0/P1
scenarios:

| scenario | treatment.opponent_used_X | baseline scripted_actions |
|---|---|---|
| anti_tr_basic | False (all turns) | trickroom executed |
| anti_tw_basic | False (all turns) | tailwind executed |
| anti_stat_boost_basic | False (all turns) | swordsdance executed |
| spread_def_heat_wave | False (all turns) | heatwave executed |

The `opponent_actions` field is
NEVER populated for scripted opps.
The flags are all `False` (default)
or the field is `None`.

**Root cause**: the audit logger's
`opponent_actions` is updated by
parsing the protocol's `move` events
where `msg[1].startswith(opp_role)`.
For scripted opps, the protocol
events for the scripted player are
processed by the scripted player's
own audit logger, not the bot's. The
bot's `turn_events` list does not
include the scripted opp's moves
(they're filtered or routed
elsewhere).

The bot's `state_snapshot.opp_active_moves_revealed`
DOES capture the opp's revealed
moves (e.g., `['heatwave']` in turn
2), but this is per-mon revealed
moves, not per-turn actions.

## 3. Canonical signal options

### 3.1 Option A: baseline `scripted_actions` as canonical

**How**: The validator reads the
baseline audit's `scripted_actions`
field. The script's recorded
execution is the canonical signal.

**Pros**:
- Works today (no code change)
- Simple, single source of truth
- Mirrors SCENARIO-5/7/8 pattern

**Cons**:
- Only works for scripted scenarios
- Loses the bot's perspective
  (opp_actions is the "natural" signal
  for non-scripted scenarios)
- Doesn't cross-check the bot's view

**Implementation**: The framework's
`expected_opp_action_used` validator
could be updated to also check the
baseline audit's `scripted_actions`.

### 3.2 Option B: bridge bot audit to capture scripted opp moves

**How**: Modify the audit logger to
process the scripted opp's protocol
events into the bot's
`opponent_actions` field.

**Pros**:
- Single source of truth (bot audit)
- Works for both scripted and
  non-scripted scenarios
- Matches the framework's existing
  validator structure

**Cons**:
- Requires audit logger changes
- Risk of new bugs in the audit
  pipeline
- The scripted opp's protocol events
  may not be available in the bot's
  protocol stream (depending on how
  poke-env routes events)
- May not be straightforward to
  implement

**Implementation**: Investigate
poke-env's protocol event routing
to see if the bot sees the
scripted opp's `move` events. If
yes, modify the audit logger's
`update_previous_turn` to parse them
into `opponent_actions`.

### 3.3 Option C: validator supports both (RECOMMENDED)

**How**: The validator reads BOTH
the treatment audit's
`opponent_actions` AND the baseline
audit's `scripted_actions`. The
canonical signal is the baseline
`scripted_actions` for scripted
scenarios. The bot's
`opponent_actions` is a
cross-check / diagnostic signal.

**Pros**:
- Works today (no code change)
- Future-proof: if the bot's audit
  starts populating `opponent_actions`
  for scripted opps, the cross-check
  is automatic
- Marks the gap explicitly (so we
  know when the bot's audit is
  incomplete)
- Mirrors SCENARIO-5/7/8 pattern
  (baseline as canonical) with
  forward compatibility

**Cons**:
- More complex validator logic
- Two signal sources to reason about

**Implementation**:
- Modify the `expected_opp_action_used`
  validator to check both:
  - Baseline audit's
    `scripted_actions` (canonical)
  - Treatment audit's
    `opponent_actions` (cross-check)
- Set a `bot_opp_action_gap` flag
  if the baseline says the action
  fired but the treatment's
    `opponent_actions.opponent_used_X`
    is False/None.
- Don't fail the scenario if the
  gap is detected; just mark it.

## 4. Policy decision

**Adopt Option C** (validator
supports both, baseline as canonical,
cross-check treatment's
`opponent_actions`).

**Rationale**:
- Works today (no code change to
  audit logger).
- The canonical signal (baseline
  `scripted_actions`) is reliable
  and matches the SCENARIO-5/7/8
  pattern.
- Cross-checking the bot's
  `opponent_actions` is
  forward-compatible: if the audit
  logger is fixed in the future,
  the validator automatically
  benefits.
- Marking `bot_opp_action_gap`
  explicitly makes the gap visible
  for future audit work without
  failing the scenario.

## 5. Decision labels

| label | status |
|---|---|
| P1_HEATWAVE_READY | ✓ TRUE (canonical signal works) |
| SPREAD_SIGNAL_GAP_NEEDS_FIX | ✓ TRUE (bot's opp_actions empty for scripted) |
| P1_BLOCKED | ✗ FALSE (canonical signal works) |

## 6. Validator policy spec (Option C)

For scripted scenarios, the
`expected_opp_action_used` validator
should:

1. **Canonical check**: Look at the
   baseline audit's
   ``scripted_actions`` for an entry
   matching ``(turn, slot, move)``
   with ``executed=True``.
2. **Cross-check**: Look at the
   treatment audit's
   ``opponent_actions.opponent_used_X``
   for the same X. If the field
   exists and is True, mark
   ``bot_opp_action_match=True``.
3. **Gap detection**: If canonical
   says fired but treatment says
   not fired, set
   ``bot_opp_action_gap=True``.
4. **Pass condition**: Pass iff
   canonical says fired.
5. **No fail on gap**: A gap is a
   diagnostic, not a fail.

The validator's return value
should include the
``bot_opp_action_gap`` flag for
observability.

## 7. Implementation plan

### 7.1 Phase 1 (SCENARIO-11, this report)

- Document the gap.
- Decide policy (Option C).
- Define validator spec.

### 7.2 Phase 2 (SCENARIO-11b, future)

- Implement the validator spec in
  ``scenario_probe.py``:
  - Modify
    ``_check_opp_action_used`` to
    read baseline audit's
    ``scripted_actions``.
  - Add cross-check against
    treatment audit's
    ``opponent_actions``.
  - Set ``bot_opp_action_gap`` flag.
- Add unit tests for the new
  validator behavior.
- Re-run SCENARIO-5/7/8/10 with the
  new validator.

### 7.3 Phase 3 (deferred, after P1 family complete)

- Investigate the audit logger
  gap: can the bot's
  ``opponent_actions`` capture the
  scripted opp's moves?
- If yes, fix the audit logger.
- If no, document the limitation
  and keep Option C as the
  long-term policy.

## 8. SCENARIO-10 reassessment

With Option C as the policy:

- **SCENARIO-10 passes**: canonical
  signal (baseline
  ``scripted_actions``) confirms
  Heat Wave fires.
- **Gap acknowledged**:
  ``bot_opp_action_gap=True`` for
  scripted scenarios (no fix
  required for SCENARIO-10 to
  pass).
- **SCENARIO-10 is ready** for the
  library.

## 9. Next steps (P1 progression)

Per the user's recommendation:

1. **SCENARIO-12 — redirection
   basic** OR **SCENARIO-12 — Rock
   Slide variant** (not Earthquake).
2. **Don't do Earthquake first**:
   grounded/Levitate/Flying
   complications make debugging
   harder than Rock Slide.
3. **If continuing spread family**,
   Rock Slide before Earthquake.

Recommended order:

- **SCENARIO-12 — redir_followme_basic**
  (family 8, P1, simpler
  semantics).
- **SCENARIO-13 — spread_def_rock_slide**
  (family 4 variant, different
  target semantics).
- **SCENARIO-14 — spread_def_earthquake**
  (family 4 variant, grounded
  complications; deferred).
- **SCENARIO-15+ — beatup_justified,
  wp, weather** (P2, custom teams
  needed).

## 10. P1 family status

| family | status |
|---|---|
| spread_def (Heat Wave) | ✓ DONE (SCENARIO-10) |
| spread_def (Rock Slide) | deferred to SCENARIO-13 |
| spread_def (Earthquake) | deferred to SCENARIO-14 |
| redir (Follow Me) | next candidate (SCENARIO-12) |

## 11. Stable state

- 0 scoring change
- 0 default flips
- 0 commit / push yet for
  SCENARIO-11
- 0 model artifacts
- 0 ``test_51`` touched
- 0 RL / V3d.1

## 12. Do-Not-Do (Final)

- No scoring change.
- No default flip.
- No ``test_51`` touched.
- No commit / push until user
  approval.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1``
  promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No SCENARIO-12+ implementation
  in this phase.
- No audit logger changes in this
  phase.
- No validator code changes in
  this phase.
- No Wide Guard scoring added.
- No planner scoring touched.

## 13. References

| source | path | role |
|---|---|---|
| SCENARIO-10 report | `logs/phaseSCENARIO10_spread_def_heat_wave_report.md` | P1 result |
| SCENARIO-10A report | `logs/phaseSCENARIO10A_p1_spread_heat_wave_probe_report.md` | P1 probe |
| SCENARIO-9 closeout | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | P0 closeout |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |
| Audit logger | `doubles_decision_audit_logger.py` | source of gap |
| Scenario framework | `scenario_probe.py` | validator source |
| SCENARIO-10 scenario | `data/curated_teams/scenarios/spread_def_heat_wave.json` | library entry |

## 14. Final Summary

- **Decisions**:
  - ``P1_HEATWAVE_READY``: TRUE
  - ``SPREAD_SIGNAL_GAP_NEEDS_FIX``: TRUE
  - ``P1_BLOCKED``: FALSE
- **Recommended policy**: Option C
  (validator supports both, baseline
  as canonical, cross-check
  treatment's `opponent_actions`,
  set `bot_opp_action_gap` flag).
- **Top 5 findings**:
  1. **The spread signal gap is
     confirmed** across all 4 P0/P1
     scenarios. The treatment
     audit's `opponent_actions` is
     empty (or `None`) for all
     scripted scenarios.
  2. **The baseline audit's
     `scripted_actions` IS the
     canonical signal** for
     scripted scenarios. Heat Wave
     fires reliably in the baseline
     audit for both SCENARIO-10
     battles.
  3. **Option C is the recommended
     policy**: validator uses
     baseline as canonical,
     cross-checks treatment's
     `opponent_actions`, sets
     `bot_opp_action_gap` flag.
     Works today (no code change)
     and is future-proof.
  4. **The audit logger gap
     (Option B) is non-trivial to
     fix**. The scripted opp's
     protocol events are processed
     by the scripted player's own
     audit, not the bot's. The
     bot's `turn_events` may not
     include the scripted opp's
     `move` events. This is a
     deeper change that should be
     deferred to Phase 3 of the
     implementation plan.
  5. **P1 progression next**:
     SCENARIO-12 (redirection
     basic) OR Rock Slide variant
     (not Earthquake). Earthquake
     deferred due to grounded
     complications.
- **Audit fields sufficient?**
  YES (via baseline
  ``scripted_actions``).
- **Exact next recommended phase**:
  **SCENARIO-11b — implement the
  Option C validator** (no battle
  run, just code + tests), then
  **SCENARIO-12 — redirection
  basic** OR Rock Slide.
- **No scoring change. No commit
  until user approval. No
  ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no
  impact when --scenario-file is
  not set).
