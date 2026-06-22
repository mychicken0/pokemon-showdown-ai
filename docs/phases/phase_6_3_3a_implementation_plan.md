# Doubles Phase 6.3.3a: Direct Absorb Adoption Correction

## Verdict

Phase 6.3.3 is not approved for default adoption in its current state.

Independent review found:

1. The full four-suite run fails:
   - 112 tests run;
   - 2 errors in `test_doubles_speed_priority.py`;
   - both errors come from subclass overrides of `check_move_will_ko` that do
     not accept the new `is_single_target_direct` keyword.
2. Run 2 selected a direct absorb-immune action that was not the only legal
   action:
   - battle `battle-gen9randomdoublesbattle-54497`, turn 5;
   - Chandelure selected Energy Ball into known Sap Sipper Goodra;
   - selected slot score was 0;
   - safe Energy Ball into Archaludon scored 43.72;
   - focus-fire joint synergy raised the blocked joint order and allowed it to
     win.
3. The walkthrough incorrectly describes this as a possible status or
   non-direct interaction. It was a direct damaging move.
4. The benchmark CSV does not contain planned battles, finished battles,
   unfinished battles, timeouts, crashes, or exceptions, so the stability gate
   is not auditable from the artifact.
5. `direct_absorb_only_legal_action` is set for every slot with one legal
   order, instead of only a selected direct-blocked action.
6. `direct_absorb_hard_block_avoided` is populated in the control-off arm even
   though no hard block was enabled.

## Immediate Default

Before any other change:

```python
ability_hard_safety_direct_absorb_only: bool = False
```

Keep it false through implementation, tests, and the correction benchmark.

Do not enable it again unless every corrected adoption gate passes.

## Restrictions

- Do not enable broad absorb safety.
- Keep redirection and ally safety disabled.
- Keep full ability awareness disabled.
- Preserve productive partial spreads.
- Use only known/revealed abilities.
- Do not infer hidden causes, moves, items, or abilities.
- Do not start Phase 7.

## Files

Modify:

- `bot_doubles_damage_aware.py`
- `bot_doubles_direct_absorb_safety_benchmark.py`
- `test_doubles_ability_hard_safety.py`
- `test_doubles_speed_priority.py` only if a test fixture compatibility change
  is genuinely required; prefer restoring production API compatibility.
- `analyze_doubles_decision_audit.py`
- `walkthrough.md`

## 1. Restore `check_move_will_ko` Compatibility

Restore the public method signature:

```python
def check_move_will_ko(self, move, active, opponent, battle=None) -> bool:
```

Remove every `is_single_target_direct=True` keyword passed to
`check_move_will_ko`.

Do not require subclasses or test doubles to update their overrides.

The direct absorb hard block already occurs in `score_action` and
`score_action_raw_damage` before KO/target bonuses can be applied. For final
audit output, explicitly record expected damage 0 and expected KO false when
the finalized action is directly blocked.

`get_expected_damage` may retain an optional explicit direct context only if
needed by direct unit tests or final audit calculation. Missing context must
remain neutral.

## 2. Prevent Joint Synergy Resurrection

Precompute whether each legal slot order is a direct known-absorb blocked
candidate under the enabled experimental flag.

For every joint order:

- retain the blocked slot's score at
  `ability_hard_safety_block_score`;
- do not apply any joint bonus or target-based synergy that depends on the
  blocked action;
- specifically skip focus-fire bonus, bulky-target double-target bonus,
  overkill logic, and order-aware target logic when either participating move
  is direct-absorb blocked;
- do not zero or discard the valid ally action's score.

The resulting joint score for one blocked action plus one valid action must be
the valid action score plus the configured blocked score, with no bonus
created by the blocked action.

Add a regression test reproducing battle 54497:

- one slot has Energy Ball into Sap Sipper Goodra with score 0;
- the same move into Archaludon has positive score;
- the ally targets Goodra;
- focus-fire synergy is enabled;
- the blocked Goodra order must not be selected.

Also test both slot positions.

## 3. Correct Final Metrics

Set:

```text
direct_absorb_only_legal_action=True
```

only when:

- the finalized selected action is a direct known-absorb blocked move; and
- the slot has exactly one legal order.

Otherwise it must be false.

Set:

```text
direct_absorb_hard_block_avoided=True
```

only when:

- `ability_hard_safety_direct_absorb_only=True`;
- at least one legal candidate was actually hard-blocked by this feature; and
- the final selected action was not directly blocked.

The control-off arm must report zero hard blocks avoided. If opportunity
tracking is useful, add a separately named diagnostic such as
`direct_absorb_candidate_available`; do not overload “hard block avoided.”

Candidate evaluation must remain side-effect free.

## 4. Correct the Existing Report

Update the Phase 6.3.3 walkthrough verdict:

- tests failed 112 run / 2 errors;
- the remaining Run 2 selection was Energy Ball into Sap Sipper;
- it was avoidable and not only legal;
- joint focus-fire synergy caused the failure;
- adoption is rejected;
- default is false pending corrected benchmark.

Do not retain the statement that every adoption gate passed.

Preserve the first benchmark as a rejected preliminary run.

## 5. Benchmark Stability Fields

The corrected benchmark CSV must include:

- `planned_battles`
- `finished_battles`
- `unfinished_battles`
- `wins`
- `losses`
- `ties_or_unknown`
- `timeouts`
- `crashes`
- `exceptions`
- `win_rate`

Validate:

```text
finished_battles == planned_battles
wins + losses + ties_or_unknown == finished_battles
unfinished_battles == 0
timeouts == 0
crashes == 0
exceptions == 0
```

Do not claim the stability gate from JSONL line count alone.

Keep all previously required behavior and safety metrics.

## 6. Tests

Add tests for:

1. legacy `check_move_will_ko` subclass overrides remain compatible;
2. blocked direct action cannot receive focus-fire synergy;
3. blocked direct action cannot receive bulky-target joint bonus;
4. valid ally action score remains intact;
5. safe target alternative beats a blocked target;
6. regression for battle 54497 in slot 0;
7. equivalent regression in slot 1;
8. only-legal metric is false for unrelated one-order slots;
9. only-legal metric is true only for selected blocked action with exactly one
   legal order;
10. avoided metric is zero when feature is off;
11. avoided metric is final-action safe when feature is on;
12. benchmark row contains all stability fields.

Run:

```bash
venv/bin/python -m unittest \
  test_doubles_ability_hard_safety.py \
  test_doubles_mechanics_scoring.py \
  test_doubles_speed_priority.py \
  test_doubles_speed_priority_analysis.py
```

Require exit code 0 with no background test processes.

## 7. Corrected Benchmark

After all tests pass, rerun the full 1,600 battles:

1. Control Off vs Basic: 500.
2. Corrected Direct On vs Basic: 500.
3. Corrected Direct On vs Control Off: 500.
4. Corrected Direct On vs SafeRandom: 100.

Write new artifacts:

```text
logs/doubles_direct_absorb_safety_corrected_benchmark.csv
logs/doubles_direct_absorb_safety_corrected_run1.jsonl
logs/doubles_direct_absorb_safety_corrected_run2.jsonl
logs/doubles_direct_absorb_safety_corrected_run3.jsonl
logs/doubles_direct_absorb_safety_corrected_run4.jsonl
```

Do not overwrite the rejected preliminary benchmark.

## 8. Corrected Adoption Gates

The original Phase 6.3.3 gates remain mandatory, plus:

- all tests pass;
- no non-only-legal direct absorb-immune move is selected in any On run;
- joint synergy never resurrects a blocked action;
- control-off hard-block-avoided count is zero;
- every stability field is present and passes;
- productive partial spreads remain preserved;
- redirected behavior remains outside the direct rule.

If any gate fails, keep:

```python
ability_hard_safety_direct_absorb_only = False
```

## Required Report

Report:

1. changed files;
2. corrected test count and exit code;
3. confirmation of restored override compatibility;
4. battle 54497 regression result;
5. all four corrected benchmark rows;
6. all stability fields;
7. direct selected, avoided, and only-legal counts;
8. productive spread and redirected counts;
9. every adoption gate;
10. final default value;
11. confirmation that broad ability awareness is disabled and Phase 7 was not
    started.
