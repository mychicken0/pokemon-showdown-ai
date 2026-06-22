# Doubles Phase 6.3.3c: Direct Absorb Final Adoption

## Decision

Adopt the corrected direct known-absorb hard safety as a default.

This is an adoption-only task. Do not alter scoring behavior.

## Evidence

Phase 6.3.3a and Phase 6.3.3b used the same corrected implementation.

Combined Basic evidence:

```text
Control Off: 1119 / 2000 = 55.95%
Direct On : 1127 / 2000 = 56.35%
Delta     : +0.40 percentage points
```

Additional gates:

- corrected Direct On vs Control Off: 51.80%;
- corrected Direct On vs SafeRandom: 95.00%;
- confirmation-only delta: +2.33 points over 1,500 battles per arm;
- zero direct absorb-immune selections across all corrected On runs;
- control-off hard-block-avoided count is zero;
- spread and focus-fire behavior preserved;
- all stability fields pass;
- 124 tests pass.

The combined result should be described as performance-neutral with a small
positive point estimate, not as conclusive proof of a performance gain.

## Restrictions

- Do not change scoring code or helpers.
- Do not rerun benchmarks.
- Do not enable broad absorb safety.
- Keep redirection and ally safety disabled.
- Keep full ability awareness disabled.
- Do not infer hidden information.
- Do not start Phase 7.

## Changes

Modify:

- `bot_doubles_damage_aware.py`
- `test_doubles_ability_hard_safety.py`
- `walkthrough.md`

## 1. Adopt the Default

Set:

```python
ability_hard_safety_direct_absorb_only: bool = True
```

Keep:

```python
enable_ability_hard_safety_only = True
ability_hard_safety_avoid_absorb = False
ability_hard_safety_avoid_redirection = False
ability_hard_safety_ally_spread_safety = False
enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
enable_threat_tiebreaker = False
```

## 2. Update Default Tests

Update only tests that assert the adopted default.

Do not weaken behavioral tests or change explicit Off/On test configurations.

Add or update a final default test that asserts the complete adopted state.

## 3. Documentation

Append Phase 6.3.3c to `walkthrough.md`.

Document:

- Phase 6.3.3a alone failed its Basic gate;
- Phase 6.3.3b was run specifically to test variance;
- confirmation-only result was +2.33 points;
- combined corrected evidence was +0.40 points over 2,000 battles per arm;
- H2H was 51.80%;
- SafeRandom was 95.00%;
- direct absorb selections were zero in corrected On runs;
- adoption is based on safety improvement and no aggregate performance
  regression under the project gate;
- statistical uncertainty remains, so do not claim a proven win-rate gain;
- exact final defaults;
- Phase 7 was not started.

Do not rewrite or delete the rejected preliminary and corrected benchmark
history.

## 4. Verification

Run:

```bash
venv/bin/python -m unittest \
  test_doubles_ability_hard_safety.py \
  test_doubles_mechanics_scoring.py \
  test_doubles_speed_priority.py \
  test_doubles_speed_priority_analysis.py
```

Require all tests to pass with exit code 0.

Do not run battles.

## Required Report

Report:

1. changed files;
2. test count and exit code;
3. exact final defaults;
4. confirmation that no benchmark was rerun;
5. confirmation that broad ability awareness remains disabled;
6. confirmation that Phase 7 was not started.
