# Phase SCENARIO-11b — Option C Canonical Signal Validator

## 1. Summary

SCENARIO-11b implements the Option C
canonical signal policy in
``scenario_probe.py``. The
``expected_scripted_action`` validator
uses the baseline audit's
``scripted_actions`` as the canonical
signal and cross-checks the treatment
audit's ``opponent_actions`` as a
diagnostic. Pass condition is based on
the canonical signal only.

**Decision**: ``OPTION_C_VALIDATOR_READY``.

The validator is implemented, unit
tested, and applied to the 4 P0/P1
artifacts. All 4 pass with
``canonical_signal_fired=True``,
``bot_opp_action_crosscheck=None``,
``bot_opp_action_gap=True`` — exactly
the documented Option C behavior.

**No battle run, no scoring change, no
default flip**.

## 2. Implementation

### 2.1 New validator type

``expected_scripted_action`` is added
to ``VALID_VALIDATOR_TYPES`` in
``scenario_probe.py``.

The validator reads the baseline
audit's ``scripted_actions`` for an
executed action matching
``validator.field`` (the move name).
It does NOT look at
``audit_turns.opponent_actions``.

### 2.2 New helper function

``validate_scripted_action_with_crosscheck``
takes a move name, baseline records,
and optional treatment records.
Returns a dict with:

- ``canonical_signal_fired``: bool
- ``bot_opp_action_crosscheck``:
  bool or None
- ``bot_opp_action_gap``: bool
- ``passed``: bool (based on canonical)
- ``message``: str

### 2.3 New runner function

``run_validators_with_canonical``
takes a scenario + baseline audit +
optional treatment audit. It runs all
validators with the correct routing:

- ``expected_scripted_action``:
  baseline as canonical, treatment as
  cross-check.
- ``expected_bot_legal_response``:
  treatment records (bot's legal
  actions are in the bot's audit).
- Others: baseline records.

### 2.4 Backward compat

The existing
``expected_opp_action_used``
validator is unchanged. Existing
scenarios that use it continue to
work (they look at
``opponent_actions.opponent_used_X``
in ``audit_turns``).

The new validator type
``expected_scripted_action`` is
additive — it doesn't change any
existing behavior.

## 3. Unit tests

Added 16 unit tests in
``TestExpectedScriptedAction``:

| # | test | what it pins |
|---|---|---|
| 1 | test_pass_when_baseline_has_move | canonical pass |
| 2 | test_fail_when_baseline_missing_move | canonical fail |
| 3 | test_fail_when_baseline_empty | empty baseline fail |
| 4 | test_gap_true_when_treatment_missing_opp_action | gap=True (opp_actions None) |
| 5 | test_gap_true_when_treatment_field_explicit_false | gap=True (False) |
| 6 | test_gap_false_when_both_agree | gap=False (both True) |
| 7 | test_no_crash_when_treatment_field_missing | no crash, gap=True |
| 8 | test_no_crash_when_treatment_records_empty | no crash, gap=False |
| 9 | test_supports_trickroom | case-insensitive |
| 10 | test_supports_tailwind | case-insensitive |
| 11 | test_supports_swordsdance | case-insensitive |
| 12 | test_supports_heatwave | case-insensitive |
| 13 | test_failed_action_does_not_count | executed=False ignored |
| 14 | test_run_validators_with_canonical | end-to-end |
| 15 | test_scenario_loader_accepts_new_type | loader accepts |
| 16 | test_scenario_loader_rejects_invalid_type | loader rejects unknown |

All 16 pass. Total tests: 84
(67 + 16 + 1 lead test).

## 4. P0/P1 artifact re-validation

Applied ``run_validators_with_canonical``
to the 4 P0/P1 artifacts (with
updated scenario files using the
new validator type):

| scenario | canonical | xcheck | gap | passed |
|---|---|---|---|---|
| anti_tr_basic | True | None | True | ✓ |
| anti_tw_basic | True | None | True | ✓ |
| anti_stat_boost_basic | True | None | True | ✓ |
| spread_def_heat_wave | True | None | True | ✓ |

All 4 pass with
``bot_opp_action_gap=True`` as
expected (the bot's audit's
``opponent_actions`` is empty for
scripted scenarios, but the canonical
signal from the baseline is reliable).

### 4.1 Updated scenario files

4 scenario files updated to use
``expected_scripted_action`` instead
of ``expected_opp_action_used`` for
the canonical signal check:

- ``anti_tr_basic.json`` (v5 → v6)
- ``anti_tw_basic.json`` (v1 → v2)
- ``anti_stat_boost_basic.json``
  (v1 → v2)
- ``spread_def_heat_wave.json``
  (v1 → v2)

The ``field`` is set to the move name
(``trickroom``, ``tailwind``,
``swordsdance``, ``heatwave``).

## 5. Anti-leak verification

- ✅ No scoring change in
  ``bot_doubles_damage_aware.py``
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1``
  promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No planner scoring touched
- ✅ No Wide Guard scoring added
- ✅ No audit logger changes
- ✅ Only ``scenario_probe.py``
  (framework) and scenario files
  (declarative) modified
- ✅ Backward compatible: existing
  ``expected_opp_action_used``
  validator still works

## 6. Do-Not-Do (Final)

- No scoring change.
- No default flip.
- No ``test_51`` touched.
- No commit / push yet.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1``
  promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No SCENARIO-12+ implementation
  in this phase.
- No audit logger changes
  (deferred to Phase 3 per
  SCENARIO-11 plan).

## 7. References

| source | path | role |
|---|---|---|
| Validator | `scenario_probe.py` | NEW validator type + helper |
| Tests | `test_scenario_probe.py` | 16 new tests |
| Scenarios | `data/curated_teams/scenarios/*.json` | updated to new validator type |
| P1 review | `logs/phaseSCENARIO11_p1_review_spread_signal_gap_report.md` | policy decision |
| P0 closeout | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | preconditions |
| Audit logger | `doubles_decision_audit_logger.py` | unchanged (gap documented) |

## 8. Final Summary

- **Decision**: ``OPTION_C_VALIDATOR_READY``.
- **Top 5 findings**:
  1. **Option C validator implemented**:
     ``expected_scripted_action``
     validator type reads baseline
     audit's ``scripted_actions`` as
     canonical. Cross-checks
     treatment's ``opponent_actions``.
     Pass based on canonical only.
  2. **16 new unit tests pass**:
     cover canonical pass/fail, gap
     detection, no-crash cases, all
     4 P0/P1 move names, end-to-end
     runner, loader accept/reject.
  3. **4 P0/P1 artifacts re-validated**:
     all pass with
     ``canonical_signal_fired=True``,
     ``bot_opp_action_crosscheck=None``,
     ``bot_opp_action_gap=True`` —
     exactly the documented Option C
     behavior.
  4. **4 scenario files updated** to
     use the new validator type.
     Backward compatible: old
     ``expected_opp_action_used``
     still works.
  5. **No audit logger changes** in
     this phase. The audit gap
     (Option B) is documented and
     deferred per the SCENARIO-11
     plan.
- **Validator policy**: Option C
  (canonical = baseline
  ``scripted_actions``, cross-check
  = treatment ``opponent_actions``,
  gap flag, pass = canonical only).
- **Exact next recommended phase**:
  **SCENARIO-12 — redirection basic
  (Follow Me / Rage Powder)** per
  the user's order:
  1. SCENARIO-12 redir_followme_basic
  2. SCENARIO-13 spread_def_rock_slide
  3. SCENARIO-14 spread_def_earthquake
     (deferred, grounded)
- **No scoring change. No commit
  yet. No ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
