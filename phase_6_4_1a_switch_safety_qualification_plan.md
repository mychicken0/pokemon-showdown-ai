# Phase 6.4.1a - Switch Safety Correctness and Qualification

Implement this correction phase before Phase 6.4.2.

## Restrictions

- Local server only.
- Do not connect to official Pokemon Showdown.
- No websites, browser automation, online APIs, or LLM calls during battles.
- Never infer hidden moves, items, or abilities.
- Keep full ability awareness disabled.
- Do not start Phase 7.
- Do not implement stat-drop-driven switching in this phase.

## Why This Correction Is Required

Codex review found that the Phase 6.4.1 battle logic is promising, but its
qualification report is not yet valid:

1. Off-run unsafe-switch metrics are always zero because diagnostics only run
   when `enable_switch_candidate_type_safety=True`. Off vs On therefore cannot
   measure whether unsafe selections decreased.
2. All 12 On-vs-Basic cases marked `unsafe selected`, `safer available`, and
   `avoided` were simultaneous double forced switches. The alleged safer
   candidate was already assigned to the other slot in the selected legal joint
   order. It was not independently available to both slots.
3. `switch_type_safety_avoided` is currently set on a final selected unsafe
   switch. That contradicts the metric definition.
4. Resistance/immunity bonuses are based on any one opposing type even when the
   same opponent's other visible type is neutral or super-effective. The design
   requires classification from the maximum visible incoming type multiplier.
5. The Phase 6.4.1 `walkthrough.md` table does not match the benchmark CSV for
   severe-negative diagnostics, double-threat counts, spread, and focus-fire.
6. Severe-negative non-switch counts include pass/default placeholders and
   repeated mid-turn requests, so they are not yet valid Phase 6.4.2 evidence.

## Part 1 - Correct Type-Safety Helper

Modify `evaluate_switch_candidate_type_safety()`.

For each visible opponent:

1. Read only its visible `type_1` and `type_2`.
2. Calculate the candidate's incoming multiplier for every available type.
3. Use the maximum multiplier as that opponent's exposure.
4. If no type/multiplier can be read, use neutral `1.0`.
5. Classify only the maximum:
   - `>= 4.0`: quad and super-effective threat
   - `>= 2.0`: super-effective threat
   - `== 0.0`: immunity bonus
   - `<= 0.5`: resistance bonus
   - otherwise neutral

Do not grant resistance or immunity bonuses merely because one type is resisted
when another visible type has a higher multiplier.

Remove the duplicated raw-score calculation and temporary explanatory comments.
Keep behavior deterministic and side-effect free.

Add tests for mixed opposing type pairs:

- resisted + neutral => neutral classification, no resistance bonus
- immune + neutral => neutral classification, no immunity bonus
- resisted + super-effective => super-effective classification only
- both resisted => resistance classification
- missing types => neutral

## Part 2 - Always-On Diagnostics, Config-Gated Scoring

Candidate type-safety diagnostics must run for both Off and On benchmark arms.

- Always evaluate legal switch candidates for audit purposes.
- Apply score adjustments only when
  `enable_switch_candidate_type_safety=True`.
- `switch_candidate_type_safety_applied` means a non-zero scoring adjustment was
  actually enabled and applicable, not merely that diagnostics ran.
- Off runs must report final unsafe selections, double-threat selections, and
  legal safer alternatives.

No diagnostic field may alter battle decisions when the feature is disabled.
Add a regression test comparing all action and joint scores with diagnostics
present but the feature disabled.

## Part 3 - Joint-Legal Switch Assignment

Switch safety in doubles must be evaluated at joint-order level.

Create structured joint-switch diagnostics for every legal joined order:

- switch candidate assigned to slot 0
- switch candidate assigned to slot 1
- per-slot raw safety
- per-slot unsafe classification
- combined switch safety score
- whether the joint assignment contains zero, one, or two unsafe candidates

Respect all legality enforced by `DoubleBattleOrder.join_orders`, including that
the same bench Pokemon cannot fill both slots.

Do not describe a candidate as a safer available alternative for a slot if using
it would make the joint order illegal because the other slot already uses it.

When both slots are forced, compare complete legal assignments, not independent
per-slot candidate maxima.

## Part 4 - Correct Metric Definitions

Replace ambiguous fields with exact selected-action/counterfactual fields:

- `final_unsafe_switch_selected`
- `final_double_threat_switch_selected`
- `legal_safer_joint_switch_available`
- `unsafe_switch_avoided_by_type_safety`
- `joint_switch_selection_changed_by_type_safety`
- `legacy_joint_switch_order`
- `legacy_joint_switch_score`
- `selected_joint_switch_safety_score`
- `unavoidable_unsafe_joint_assignment`
- `joint_switch_assignment_reason`

Definitions:

### final_unsafe_switch_selected

The final selected candidate for this slot is quad-weak or threatened
super-effectively by both visible opposing active Pokemon.

### legal_safer_joint_switch_available

At least one complete legal joint order exists that uses a safer candidate in
this slot. Report the impact on the other slot too. Do not use an independently
computed candidate that conflicts with the other selected switch.

### unsafe_switch_avoided_by_type_safety

True only when:

1. the best joint order under legacy scores would select an unsafe candidate for
   this slot;
2. the best joint order after type-safety adjustments selects a safer candidate;
3. both orders are complete and legal;
4. the selected action actually changed.

It must never be true when the final selected switch is still the same unsafe
candidate.

### unavoidable_unsafe_joint_assignment

True when the request requires multiple replacements and every complete legal
joint switch assignment contains at least one unsafe candidate.

Preserve old JSON keys temporarily only if compatibility requires them, but mark
them deprecated and map them to semantically correct values. Update analyzer,
inspector, CSV, and documentation to use the new names.

## Part 5 - Counterfactual Selection

Before applying Phase 6.4.1 switch adjustments:

1. calculate and retain the best complete legal joint order using legacy scores;
2. apply switch safety adjustments;
3. calculate the actual best complete legal joint order;
4. compare both deterministically using the same tie-breaking behavior.

This counterfactual is audit-only. Do not execute the legacy order.

Ensure normal move synergy logic is treated consistently in both comparisons so
the reported changed selection is real rather than an artifact of comparing
different scoring stages.

## Part 6 - Negative-Boost Diagnostic Eligibility

Do not change scoring based on boosts.

Add:

- `negative_boost_decision_eligible`
- `negative_boost_selected_action_kind`
- `negative_boost_legal_switch_count`
- `negative_boost_best_switch_species`
- `negative_boost_best_switch_score`
- `negative_boost_best_move_score`
- `negative_boost_switch_score_gap`
- `negative_boost_relevant_offensive_drop`
- `negative_boost_defensive_drop`
- `negative_boost_speed_drop`

A negative-boost decision is eligible only when:

- the active Pokemon exists and is not fainted;
- its slot is not force-switching;
- it has at least one legal voluntary switch;
- it has at least one genuine selectable move/action;
- the selected order is not pass/default;
- it is not a duplicate placeholder audit from a mid-turn replacement request.

Deduplicate counts by a stable decision-event identifier. A repeated audit call
for the same battle, turn, slot, active identity, and request state must not
inflate totals.

Separate:

- offensive drops relevant to available physical/special damaging moves;
- defensive drops;
- speed drops;
- self-inflicted repeated-drop cases when detectable from already known action
  history, without guessing hidden information.

## Part 7 - Analyzer and Inspector

Update `analyze_doubles_decision_audit.py` and
`inspect_switch_candidate_safety_cases.py`.

Required inspector filters:

- `--final-unsafe`
- `--legal-safer-joint`
- `--avoided`
- `--selection-changed`
- `--unavoidable-assignment`
- `--eligible-negative-boost`
- `--offensive-drop`
- `--defensive-drop`
- `--speed-drop`
- `--battle`
- `--filepath`

Handle piped output without a `BrokenPipeError` traceback.

The analyzer must report Off and On metrics using identical definitions and
explicitly separate:

- candidate actions
- selected slot actions
- selected joint decisions
- unique eligible negative-boost decisions
- battles containing each event

## Part 8 - Tests

Add or update tests for:

1. corrected max-multiplier resistance/immunity classification;
2. diagnostics present with feature Off but scores unchanged;
3. simultaneous forced switches use complete legal assignments;
4. candidate occupied by the other slot is not called independently available;
5. selected unsafe is never simultaneously counted as avoided;
6. avoided requires a changed legal legacy-vs-enabled selection;
7. unavoidable unsafe assignment classification;
8. single-slot forced switch classification;
9. counterfactual tie behavior is deterministic;
10. negative-boost pass/default exclusion;
11. forced-switch exclusion from negative-boost eligibility;
12. no-legal-switch exclusion;
13. duplicate event deduplication;
14. relevant physical vs special offensive drops;
15. inspector broken-pipe handling;
16. CSV and walkthrough values match source artifacts.

Run the existing five suites plus the new correction tests.

## Part 9 - Corrected Qualification Benchmark

After all tests pass, rerun:

- Off vs Basic: 500
- On vs Basic: 500
- On vs Off: 500
- On vs SafeRandom: 100

Save new artifacts with `phase641a` in each filename. Do not overwrite Phase
6.4.1 artifacts.

Report for both Off and On:

- final unsafe switches selected
- final double-threat switches selected
- legal safer joint available
- unsafe switches avoided
- joint selections changed
- unavoidable unsafe joint assignments
- single and double forced-switch counts
- voluntary switch counts
- spread, focus-fire, Protect
- stability fields
- unique eligible severe-negative decisions by drop category

## Part 10 - Adoption Re-evaluation

Re-evaluate `enable_switch_candidate_type_safety`.

Keep it `True` only if corrected evidence shows:

- tests and stability pass;
- final unsafe selections decrease against a measured Off baseline;
- unsafe avoided cases are semantically valid;
- On vs Basic regression is no worse than -2 percentage points;
- On vs Off is at least 50%;
- On vs SafeRandom is at least 95%;
- voluntary switching, spread, and focus-fire do not collapse.

If a gate fails, set the default back to `False` but preserve code and artifacts.

Do not begin Phase 6.4.2 until this requalification is complete.

## Part 11 - Documentation

Correct `walkthrough.md` rather than appending contradictory claims.

Explicitly document:

- the invalid Phase 6.4.1 metric assumptions;
- why the 12 cases were simultaneous double-switch assignment conflicts;
- exact corrected CSV values;
- corrected negative-boost eligible counts;
- final adoption decision and defaults;
- Phase 6.4.2 remains unstarted;
- Phase 7 remains unstarted.

## Final Report

Return:

1. changed files;
2. test count and exit code;
3. corrected helper behavior;
4. corrected four benchmark rows;
5. Off-vs-On joint-legality safety metrics;
6. eligible negative-boost evidence by category;
7. adoption decision and exact defaults;
8. confirmation that Phase 6.4.2 scoring and Phase 7 were not started.
