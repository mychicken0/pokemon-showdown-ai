# Doubles Phase 6.3.3b: Direct Absorb Variance Confirmation

## Objective

Determine whether the Phase 6.3.3a `-5.40` percentage-point regression versus
`DoublesBasicAwarePlayer` is reproducible or benchmark variance.

This phase is benchmark-only.

## Restrictions

- Do not change battle scoring.
- Do not change any default configuration.
- Keep `ability_hard_safety_direct_absorb_only=False`.
- Keep broad absorb, redirection, ally safety, and full ability awareness
  disabled.
- Use the local Pokémon Showdown server only.
- Do not connect to the official server or any online service.
- Do not infer hidden moves, items, or abilities.
- Do not start Phase 7.

## Files

Create:

- `bot_doubles_direct_absorb_confirmation_benchmark.py`

Modify:

- `walkthrough.md` after the benchmark completes.

Do not modify `bot_doubles_damage_aware.py` or scoring tests in this phase.

## Benchmark Design

Use the exact adopted Ground-only control configuration. The experimental
configuration differs only by:

```python
ability_hard_safety_direct_absorb_only=True
```

Run six independent 500-battle blocks against
`DoublesBasicAwarePlayer`, alternating execution order:

1. Control Off vs Basic: 500.
2. Direct On vs Basic: 500.
3. Direct On vs Basic: 500.
4. Control Off vs Basic: 500.
5. Control Off vs Basic: 500.
6. Direct On vs Basic: 500.

Total: 3,000 battles.

Use a new bot/opponent username suffix for every block.

Do not reuse or overwrite Phase 6.3.3/6.3.3a artifacts.

## Output Artifacts

Write:

```text
logs/doubles_direct_absorb_confirmation_benchmark.csv
logs/doubles_direct_absorb_confirmation_run1.jsonl
logs/doubles_direct_absorb_confirmation_run2.jsonl
logs/doubles_direct_absorb_confirmation_run3.jsonl
logs/doubles_direct_absorb_confirmation_run4.jsonl
logs/doubles_direct_absorb_confirmation_run5.jsonl
logs/doubles_direct_absorb_confirmation_run6.jsonl
```

## Required Per-Block Fields

- run number;
- variant;
- execution order;
- planned battles;
- finished battles;
- unfinished battles;
- wins;
- losses;
- ties or unknown;
- win rate;
- average turns;
- timeouts;
- crashes;
- exceptions;
- Protect count;
- spread count;
- focus-fire count;
- ground into Levitate selected;
- direct absorb hard blocks avoided;
- direct absorb-immune moves selected;
- direct absorb only-legal selections;
- redirected absorb selections;
- productive partial absorb spreads;
- zero-effectiveness moves;
- all-target immune spreads.

## Aggregate Report

Print and append aggregate rows for:

- Control Off: 1,500 battles.
- Direct On: 1,500 battles.

For each variant report:

- total wins/losses;
- aggregate win rate;
- mean block win rate;
- minimum and maximum block win rate;
- population standard deviation across the three block win rates;
- aggregate average turns;
- all behavior and safety metrics.

Calculate:

```text
aggregate_delta_pp = Direct On aggregate win rate - Control Off aggregate win rate
```

Also print each paired chronological comparison:

- Run 2 On minus Run 1 Off;
- Run 3 On minus Run 4 Off;
- Run 6 On minus Run 5 Off.

These paired values are diagnostic only; aggregate delta is the primary
decision metric.

## Stability Validation

For every block require:

```text
finished_battles == planned_battles
wins + losses + ties_or_unknown == finished_battles
unfinished_battles == 0
timeouts == 0
crashes == 0
exceptions == 0
```

Abort without an adoption recommendation if any stability condition fails.

## Pre-Benchmark Verification

Before starting battles:

1. Verify `ability_hard_safety_direct_absorb_only=False` in the default config.
2. Run the existing four test suites.
3. Require all 124 or more tests to pass with exit code 0.
4. Verify the local server responds at `localhost:8000`.

Do not change files to make a failing test pass. Stop and report the failure.

## Confirmation Decision

This phase does not enable the flag automatically.

Classify the result:

### Reproducible Regression

If:

```text
aggregate_delta_pp < -2.00
```

then:

- confirm adoption rejection;
- keep the flag false;
- recommend no further direct-absorb scoring work in Phase 6;
- preserve the implementation as disabled diagnostic code.

### Performance-Neutral Confirmation

If:

```text
-2.00 <= aggregate_delta_pp <= 2.00
```

then:

- classify the original regression as likely variance;
- keep the flag false pending Codex review;
- do not enable automatically;
- report whether every individual On block avoided non-only-legal direct
  absorb selections.

### Positive Confirmation

If:

```text
aggregate_delta_pp > 2.00
```

then:

- classify the feature as performance-positive;
- keep the flag false pending Codex review;
- do not enable automatically.

## Documentation

Update `walkthrough.md` with:

- confirmation objective and restrictions;
- all six block rows;
- two aggregate rows;
- paired deltas;
- aggregate delta;
- stability results;
- safety and behavior metrics;
- classification under the rules above;
- final unchanged defaults;
- Phase 7 confirmation.

## Required Final Report

Report:

1. changed files;
2. test count and exit code;
3. all six benchmark blocks;
4. Control and On aggregate rows;
5. aggregate and paired deltas;
6. stability validation;
7. direct selected/avoided/only-legal metrics;
8. spread, focus-fire, redirected, and productive spread metrics;
9. classification;
10. confirmation that defaults were unchanged and Phase 7 was not started.
