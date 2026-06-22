# Doubles Phase 6.3.2b: Absorb Report Classification Cleanup

## Objective

Correct the Phase 6.3.2a reporting and inspector defects without changing
battle scoring, defaults, or rerunning the 400-battle audit.

The raw run2 diagnostic fields are usable. This task fixes how they are
classified and presented.

## Review Findings

1. `inspect_absorb_error_cases.py` defaults every selected event to
   `AVOIDABLE`. This falsely labels events where
   `avoidable_absorb_error=False`.
2. The analyzer sample classification uses the same forced/productive/else
   pattern and therefore also labels unclassified events as avoidable.
3. In run2 SafeRandom, 12 Basculegion Wave Crash actions have:
   - `avoidable_absorb_error=False`
   - `absorb_selection_forced=False`
   - `productive_partial_absorb_spread=False`
   - `absorb_safe_alternative_available=False`

   They had a positively scored switch available, so they are neither forced
   nor avoidable under the current damaging-alternative definition.
4. The walkthrough calls Basculegion “locked into Wave Crash,” but no
   diagnostic proves a move lock. Do not infer an item, Encore, or other hidden
   cause.
5. The walkthrough says the attacker switched move to Scald on turn 21. The
   attacker actually changed from Basculegion to Slowking.
6. The run2 CSV still uses ambiguous legacy column names even though the plan
   required explicit action-level and battle-level units.
7. `inspect_ability_hard_safety_cases.py` was not updated to display the new
   intended/effective target fields.

## Restrictions

- Do not change `score_action`, `get_expected_damage`, or joint-order scoring.
- Do not change any config default.
- Do not rerun battles.
- Use the existing run2 JSONL files to regenerate reports and CSV.
- Do not infer hidden moves, items, abilities, or causes.
- Do not start Phase 7.

## Files

Modify:

- `analyze_doubles_decision_audit.py`
- `inspect_absorb_error_cases.py`
- `inspect_ability_hard_safety_cases.py`
- `bot_doubles_absorb_error_audit.py`
- `test_doubles_ability_hard_safety.py`
- `walkthrough.md`

## 1. Add an Exhaustive Classification Helper

Create one shared pure helper, or equivalent identical logic, that returns
exactly one class:

```text
FORCED_NO_USEFUL_SCORED_ALT
AVOIDABLE_SAFE_DAMAGE_ALT
PRODUCTIVE_PARTIAL_SPREAD
OTHER_USEFUL_SCORED_ALT
UNCLASSIFIED
```

Precedence:

1. `productive_partial_absorb_spread=True`
   -> `PRODUCTIVE_PARTIAL_SPREAD`
2. `avoidable_absorb_error=True`
   -> `AVOIDABLE_SAFE_DAMAGE_ALT`
3. `absorb_selection_forced=True`
   -> `FORCED_NO_USEFUL_SCORED_ALT`
4. selected absorb event with
   `absorb_safe_alternative_available=False` and forced false
   -> `OTHER_USEFUL_SCORED_ALT`
5. otherwise -> `UNCLASSIFIED`

The fourth class means the original classifier found a positive-score switch
or status action. Do not call it avoidable unless a separate field proves
that claim.

## 2. Fix Inspectors

Both inspectors must:

- use the exhaustive classification;
- never default to `AVOIDABLE`;
- print the raw booleans for forced, safe damaging alternative, productive
  spread, and avoidable;
- print direct/redirected, intended target, effective target, and abilities;
- print attacker, selected move ID, canonical score, alternative, streak, and
  outcome.

`--avoidable-absorb` must return only events with
`avoidable_absorb_error=True`.

Add an optional filter:

```text
--other-useful-alt
```

It must select the fourth class only.

## 3. Fix Analyzer

Add action counts for all five exhaustive classes.

The sum of class counts must equal `absorb_selected_action_count`.

Print a consistency line:

```text
classified_total == selected_total: PASS/FAIL
```

Sample labels must use the same classification helper and must not convert
unknown classes into avoidable.

## 4. Fix CSV Units

Regenerate `logs/doubles_absorb_error_audit_run2_summary.csv` from the existing
run2 JSONL files with explicit columns:

- `absorb_selected_action_count`
- `absorb_avoidable_action_count`
- `forced_no_useful_scored_alt_action_count`
- `productive_partial_spread_action_count`
- `other_useful_scored_alt_action_count`
- `unclassified_action_count`
- `direct_absorb_selected_action_count`
- `redirected_absorb_selected_action_count`
- `direct_avoidable_absorb_action_count`
- `redirected_avoidable_absorb_action_count`
- `battles_with_absorb_selected_win`
- `battles_with_absorb_selected_loss`
- `battles_with_absorb_avoidable_win`
- `battles_with_absorb_avoidable_loss`
- equivalent explicit battle columns for forced and productive spread.

Remove or stop emitting ambiguous names such as
`wins_absorb_selected` and `absorb_selected_count`.

Add a CLI mode to the audit script that summarizes existing logs without
starting players:

```bash
venv/bin/python bot_doubles_absorb_error_audit.py --summarize-existing
```

This command must not connect to any server.

## 5. Correct the Walkthrough

Correct the Phase 6.3.2a section:

- Do not call the 12 Wave Crash actions avoidable.
- Do not claim Basculegion was move-locked.
- State that a useful scored switch/status alternative existed under the
  current classifier, but no safe damaging alternative existed.
- Correct turn 21: Basculegion left the field and Slowking selected Scald.
- Clearly separate action counts from battle counts.
- Preserve the conclusion that direct avoidable errors were 6/7 against Basic,
  while noting the sample is small.

## 6. Tests

Add tests for:

1. selected event with all three primary flags false is not labeled avoidable;
2. `OTHER_USEFUL_SCORED_ALT` classification;
3. all five classes are mutually exclusive;
4. class totals equal selected totals;
5. `--avoidable-absorb` excludes other-useful-alt events;
6. `--other-useful-alt` returns only matching events;
7. analyzer sample labels match raw flags;
8. summarize-existing mode performs no battle/server initialization;
9. regenerated CSV uses explicit unit names.

Run all four suites and require exit code 0.

## 7. Verification Using Existing Logs

Run:

```bash
venv/bin/python bot_doubles_absorb_error_audit.py --summarize-existing
venv/bin/python analyze_doubles_decision_audit.py \
  logs/doubles_absorb_error_audit_run2_vs_basic.jsonl
venv/bin/python analyze_doubles_decision_audit.py \
  logs/doubles_absorb_error_audit_run2_vs_safe_random.jsonl
venv/bin/python inspect_absorb_error_cases.py \
  --other-useful-alt \
  --battle battle-gen9randomdoublesbattle-53506 \
  --filepath logs/doubles_absorb_error_audit_run2_vs_safe_random.jsonl
```

Expected raw-log classification:

- Basic: selected 10, avoidable 7, productive 2,
  other-useful-scored-alt 1, forced 0, unclassified 0.
- SafeRandom: selected 19, avoidable 7, productive 0,
  other-useful-scored-alt 12, forced 0, unclassified 0.

## Decision After Cleanup

Do not implement scoring in this task.

The next proposed scoring phase remains a benchmarked
`single-target direct known-absorb hard safety` ablation because 6 of 7
avoidable actions against Basic were direct. Redirection must remain a
separate ablation, and productive partial spreads must be preserved.

The evidence is small, so no absorb behavior should become a default without
the Phase 6.3.3 benchmark and adoption gates.

## Required Report

Report:

1. changed files;
2. tests and exit code;
3. corrected exhaustive class counts for both logs;
4. regenerated CSV header;
5. inspector verification for battle 53506;
6. confirmation that no battles were rerun;
7. confirmation that defaults are unchanged and Phase 7 was not started.
