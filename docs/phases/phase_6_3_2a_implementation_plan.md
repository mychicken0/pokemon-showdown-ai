# Doubles Phase 6.3.2a: Absorb Diagnostic Correctness

## Objective

Correct the Phase 6.3.2 absorb diagnostics before using them to choose a
scoring intervention.

This phase remains diagnostic-only. Do not change battle scoring or defaults.

## Review Findings

The implementation passes all 81 relevant tests, but the real audit exposed
three diagnostic issues:

1. Consecutive redirected Liquidation selections on turns 2 and 3 were both
   recorded with streak 1. The current state is slot-based and is not
   idempotent when `choose_move` is evaluated more than once in a turn.
2. Redirected Storm Drain and Lightning Rod cases record the intended target,
   while the effective redirecting target species and ability are empty.
3. Safe alternative ranking recomputes `score_action` with different flags
   instead of using the canonical precomputed candidate score used to select
   the joint order.

The current logs therefore cannot reliably support a repeat-only scoring rule.

## Restrictions

- Keep the adopted Ground-only defaults unchanged.
- Keep `ability_hard_safety_avoid_absorb=False`.
- Keep `ability_hard_safety_avoid_redirection=False`.
- Keep `ability_hard_safety_ally_spread_safety=False`.
- Keep `enable_ability_awareness=False`.
- Use only explicitly revealed abilities.
- Do not infer abilities from species, possible abilities, or random-set data.
- Do not change scoring in this phase.
- Do not start Phase 7.

## Files

Modify:

- `bot_doubles_damage_aware.py`
- `doubles_decision_audit_logger.py`
- `analyze_doubles_decision_audit.py`
- `inspect_ability_hard_safety_cases.py`
- `inspect_absorb_error_cases.py`
- `bot_doubles_absorb_error_audit.py`
- `test_doubles_ability_hard_safety.py`
- `walkthrough.md`

## 1. Make Streak Tracking Idempotent

Track the finalized absorb event by stable attacker identity, not only active
slot. Use the existing Pokémon identifier helper where possible.

The streak key must contain:

```text
attacker identity + move ID + effective blocked target identity + block reason
```

Required behavior:

- Same event evaluated again on the same battle turn preserves the existing
  streak and does not reset or increment it.
- Same event on the immediately following turn increments the streak.
- A different move, effective target, reason, attacker, non-absorb action, or
  turn gap resets the streak.
- Switching positions must not reset a continuing event solely because the
  same attacker moved from slot 0 to slot 1.
- Candidate scoring must never mutate streak state.

Add a regression test reproducing two `choose_move` evaluations on turn N,
followed by the same selected absorb event on turn N+1. The final streak must
be 2, not 1.

Add a test where the same attacker changes active slot between consecutive
turns and the same effective event still increments correctly.

## 2. Record Intended and Effective Targets

Add final-action diagnostic fields:

- `absorb_via_redirection`
- `absorb_intended_target_species`
- `absorb_intended_target_ability`
- `absorb_effective_target_species`
- `absorb_effective_target_ability`
- `absorb_selected_move_id`

For direct ability blocks, intended and effective target are the same.

For Storm Drain or Lightning Rod redirection:

- intended target is the selected slot;
- effective target is the known redirector;
- effective target ability is `stormdrain` or `lightningrod`;
- streak identity uses the effective target;
- inspectors and analyzer must print both targets clearly.

Do not overload the existing enabled-safety fields
`ability_blocked_target_species` and `ability_blocked_target_ability` for this
diagnostic.

## 3. Use Canonical Candidate Scores

Refactor safe-alternative checking into:

1. a pure safety predicate; and
2. the precomputed score from `slot_0_scores` or `slot_1_scores`.

Do not call `score_action` again to rank the alternative.

The recorded `absorb_best_safe_alternative_score` must exactly equal the
candidate score used in joint-order selection for that legal order.

Add tests for:

- exact canonical score preservation;
- no audit or streak mutation while checking alternatives;
- a redirected candidate being excluded as unsafe;
- a productive partial spread not selecting itself as a misleading “best
  alternative.”

## 4. Clarify Classification and Units

Keep action-level and battle-level metrics separate.

Rename or add CSV columns so their units are explicit:

- `absorb_selected_action_count`
- `absorb_avoidable_action_count`
- `battles_with_absorb_selected_win`
- `battles_with_absorb_selected_loss`
- equivalent battle columns for avoidable, forced, and productive spread.

Add separate action counts:

- `direct_absorb_selected_count`
- `redirected_absorb_selected_count`
- `direct_avoidable_absorb_count`
- `redirected_avoidable_absorb_count`

Reports must say “per 100 battles” where that denominator is used. Do not call
3.67 or 5.00 a percentage of turns without calculating total audited turns.

`absorb_selection_forced` means no positive-score safe damaging alternative,
positive-score switch, or positive-score status action under the existing
Phase 6.3.2 definition. Label this explicitly as “no useful scored
alternative,” not “no legal alternative.”

## 5. Analyzer and Inspector Output

Update both inspectors and the analyzer to print:

- selected move ID;
- intended target and known ability;
- effective target and known ability;
- direct versus redirected classification;
- selected canonical score;
- best safe alternative and canonical score;
- streak;
- battle outcome.

Bot-only filters must continue to exclude opponent errors.

## 6. Tests

Run:

```bash
venv/bin/python -m unittest \
  test_doubles_ability_hard_safety.py \
  test_doubles_mechanics_scoring.py \
  test_doubles_speed_priority.py \
  test_doubles_speed_priority_analysis.py
```

All tests must exit cleanly with code 0. Do not leave Python or battle
processes running in the background.

## 7. Corrected Audit

Rerun the unchanged adopted default:

- vs `DoublesBasicAwarePlayer`: 300 battles;
- vs `DoublesSafeRandomPlayer`: 100 battles.

Write new artifacts without overwriting the first audit:

- `logs/doubles_absorb_error_audit_run2_vs_basic.jsonl`
- `logs/doubles_absorb_error_audit_run2_vs_safe_random.jsonl`
- `logs/doubles_absorb_error_audit_run2_summary.csv`

Verify at least one known redirection sample manually through the inspector.
Verify any consecutive repeat sample against adjacent raw audit turns.

## 8. Decision Gate for Phase 6.3.3

Do not implement Phase 6.3.3 in this task.

After the corrected audit:

- Prefer `single-target direct known-absorb hard safety` if direct avoidable
  actions remain the dominant error class.
- Evaluate redirection as a separate later ablation; do not bundle it with
  direct absorb safety.
- Consider repeat-only anti-spam only if corrected streak data shows that
  repetition accounts for a substantial share of avoidable actions.
- Preserve productive partial spread moves.
- Do not enable broad absorb safety by default without a benchmark.

## Required Report

Report:

1. changed files;
2. all test counts and exit code;
3. direct versus redirected action counts;
4. corrected streak distribution and manually verified samples;
5. productive partial spread count;
6. action-level versus battle-level win/loss counts;
7. recommendation for Phase 6.3.3;
8. confirmation that defaults are unchanged and Phase 7 was not started.
