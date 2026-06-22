# Doubles Phase 6.3.3: Direct Known-Absorb Hard Safety

## Objective

Implement and benchmark a narrow hard-safety rule for single-target damaging
moves aimed directly at an opponent with a known absorb/benefit ability.

This phase must not include redirection safety, spread-move absorb safety, ally
ability safety, full ability awareness, or speculative ability inference.

## Evidence

The corrected Phase 6.3.2 run2 audit found:

- vs Basic: 7 avoidable absorb actions, 6 direct and 1 redirected;
- vs SafeRandom: 7 avoidable absorb actions, 3 direct and 4 redirected;
- productive partial spreads occurred and must remain usable;
- the sample is small, so adoption requires a controlled benchmark.

## Restrictions

- Local Showdown server only.
- Never connect to the official server.
- No websites, browser automation, online APIs, or LLM calls in battle.
- Use only explicitly revealed/known abilities through `get_known_ability`.
- Never infer an ability from species, possible abilities, or random sets.
- Keep `enable_ability_awareness=False`.
- Keep `ability_hard_safety_avoid_redirection=False`.
- Keep `ability_hard_safety_ally_spread_safety=False`.
- Do not alter spread move scoring in this phase.
- Do not start Phase 7.

## Files

Modify:

- `bot_doubles_damage_aware.py`
- `doubles_decision_audit_logger.py`
- `analyze_doubles_decision_audit.py`
- `inspect_absorb_error_cases.py`
- `test_doubles_ability_hard_safety.py`
- `walkthrough.md`

Create:

- `bot_doubles_direct_absorb_safety_benchmark.py`

## 1. Add a Separate Config Flag

Add:

```python
ability_hard_safety_direct_absorb_only: bool = False
```

Keep it `False` by default until the adoption gates pass.

Do not repurpose `ability_hard_safety_avoid_absorb`; it represents the broader
Phase 6.3 behavior and must remain `False`.

The adopted Ground-only configuration remains active independently:

```python
enable_ability_hard_safety_only = True
ability_hard_safety_avoid_absorb = False
ability_hard_safety_avoid_redirection = False
ability_hard_safety_ally_spread_safety = False
```

## 2. Direct Absorb Helper

Create:

```python
def direct_known_absorb_blocks_move(move, attacker, target, battle=None) -> tuple[bool, str]:
    ...
```

Rules:

- damaging move only;
- intended target must be the directly selected opponent;
- use only `ability_hard_blocks_move` and `get_known_ability`;
- return true only for these known absorb reasons:
  - Water Absorb
  - Storm Drain
  - Dry Skin
  - Volt Absorb
  - Motor Drive
  - Lightning Rod
  - Flash Fire
  - Well-Baked Body
  - Sap Sipper
- preserve Mold Breaker, Teravolt, and Turboblaze bypass behavior;
- unknown abilities never block;
- do not search the other opponent for a redirector;
- do not apply to spread moves.

## 3. Scoring Integration

When all are true:

- `enable_ability_hard_safety_only=True`;
- `ability_hard_safety_direct_absorb_only=True`;
- selected order is a single-target damaging move;
- intended opponent is directly blocked by a known absorb ability;

then:

- target expected damage is `0.0`;
- expected KO is `False`;
- final action score is `ability_hard_safety_block_score`;
- do not add KO, HP targeting, focus-fire, threat, or other target bonuses.

This must behave like the adopted Ground direct-target hard block.

Do not change:

- spread moves, including productive partial absorb spreads;
- Water/Electric moves aimed at the other slot when Storm Drain or Lightning
  Rod is present;
- ally-hit spread evaluation;
- status moves;
- unknown abilities.

If the blocked action is the only legal action, selection may still occur.
The metric must distinguish selected despite block from avoided candidate.

## 4. Damage API Context

Do not accidentally apply direct-only safety while evaluating a spread move
target-by-target.

If `get_expected_damage` needs configuration/context, pass an explicit
single-target-direct context from `score_action`. Missing context must leave
the new rule disabled.

Add a regression test proving that a spread move into one known absorb target
still scores damage against the other target and is unchanged by the new flag.

## 5. Audit Metrics

Add final selected-action metrics:

- `direct_absorb_hard_block_avoided`
- `direct_absorb_immune_move_selected`
- `direct_absorb_block_reason`
- `direct_absorb_target_species`
- `direct_absorb_target_ability`
- `direct_absorb_only_legal_action`

Definitions:

- `direct_absorb_hard_block_avoided`: at least one legal direct known-absorb
  candidate was hard-blocked and the final selected action was not such a
  candidate.
- `direct_absorb_immune_move_selected`: final selected action still directly
  targeted a known absorb-immune opponent.
- `direct_absorb_only_legal_action`: the selected blocked action had no other
  legal order for that slot.

Count only finalized selected actions for selected metrics. Candidate checks
must not inflate counts.

Continue reporting direct and redirected absorb events separately.

## 6. Analyzer and Inspector

Add a `Direct Absorb Safety Report` containing:

- direct hard blocks avoided;
- direct absorb-immune moves selected;
- only-legal-action selections;
- reason split;
- win/loss action counts;
- battle counts;
- sample attacker, move, target, known ability, reason, selected score, and
  best alternative.

Add inspector filters:

```text
--direct-block-avoided
--direct-immune-selected
--direct-only-legal
```

Do not mix redirected events or opponent mistakes into these filters.

## 7. Unit Tests

Add tests for:

1. Water Absorb blocks a directly targeted Water damaging move.
2. Storm Drain blocks a Water move directly targeting the Storm Drain user.
3. Volt Absorb blocks a direct Electric move.
4. Motor Drive, Lightning Rod, Flash Fire, Well-Baked Body, Dry Skin, and Sap
   Sipper direct blocks.
5. Unknown ability does not block.
6. Mold Breaker/Teravolt/Turboblaze bypass.
7. Status moves are unchanged.
8. Direct blocked action score, damage, and expected KO are zero/false with no
   target bonuses.
9. Productive partial spread is unchanged.
10. All-target absorb spread is unchanged in this phase.
11. Storm Drain redirection is unchanged and not classified as a direct block.
12. Lightning Rod redirection is unchanged and not classified as a direct
    block.
13. Candidate hard block avoided metric is final-action safe.
14. Selected blocked metric counts only the final action.
15. Only-legal-action selection is classified correctly.
16. Default flag remains false before adoption.
17. Existing adopted Ground-only defaults remain unchanged.

Run all four existing suites with exit code 0 and no background processes.

## 8. Benchmark

Create `bot_doubles_direct_absorb_safety_benchmark.py`.

Use the adopted Ground-only defaults as the control. Change only
`ability_hard_safety_direct_absorb_only`.

Run:

1. Control Off vs `DoublesBasicAwarePlayer`: 500 battles.
2. Direct Absorb On vs `DoublesBasicAwarePlayer`: 500 battles.
3. Direct Absorb On vs Control Off: 500 battles.
4. Direct Absorb On vs `DoublesSafeRandomPlayer`: 100 battles.

Save:

```text
logs/doubles_direct_absorb_safety_benchmark.csv
logs/doubles_direct_absorb_safety_*.jsonl
```

Do not overwrite Phase 6.3.1 or Phase 6.3.2 logs.

Print and save:

- wins, losses, win rate, average turns;
- Protect, spread, and focus-fire usage;
- ground into Levitate selected;
- direct absorb hard blocks avoided;
- direct absorb-immune moves selected;
- redirected absorb selections;
- productive partial absorb spreads;
- only-legal-action blocked selections;
- zero-effectiveness moves;
- all-target immune spreads;
- crashes, timeouts, or unfinished battles.

## 9. Adoption Gates

Enable `ability_hard_safety_direct_absorb_only=True` by default only if:

- all tests pass;
- all 1,600 battles finish with no crash or deadlock;
- direct absorb-immune selections fall to near zero except genuinely
  only-legal-action cases;
- productive partial spread usage is preserved;
- redirected behavior remains outside this rule;
- On vs Basic is no worse than Control by more than 2 percentage points;
- On vs Off is at least 50%;
- On vs SafeRandom is at least 95%;
- spread usage does not decline by more than 15% versus control;
- focus-fire usage does not decline by more than 15% versus control;
- Ground-only safety remains effective.

If any gate fails:

- keep the implementation, tests, audit, analyzer, and benchmark;
- keep `ability_hard_safety_direct_absorb_only=False`;
- document the exact failed gate.

Do not enable `ability_hard_safety_avoid_absorb`.

## 10. Documentation

Update `walkthrough.md` with:

- Phase 6.3.3 implementation;
- exact distinction between direct absorb, redirection, and spread;
- test results;
- all four benchmark results;
- safety and behavior metrics;
- adoption gate evaluation;
- final default configuration;
- confirmation that Phase 7 was not started.

## Required Report

Report:

1. changed files;
2. test counts and exit code;
3. all four benchmark rows;
4. direct selected/avoided/only-legal counts;
5. redirected and productive spread preservation;
6. every adoption gate;
7. final default value of
   `ability_hard_safety_direct_absorb_only`;
8. confirmation that full ability awareness remains disabled and Phase 7 was
   not started.
