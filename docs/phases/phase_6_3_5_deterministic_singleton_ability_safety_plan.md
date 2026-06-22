# Phase 6.3.5 - Deterministic Singleton Ability Hard Safety

Implement deterministic hard safety for opponents whose exact species/form has
only one legal ability in the local generation data. This is a narrow exception
to the previous revealed-only policy and is explicitly approved by the user.

This is not probabilistic ability prediction and must not enable full ability
awareness.

## Mandatory Execution Watchdog Policy

Apply this policy to every command run during this task.

### Shell commands

Wrap tests, analyzers, inspectors, smoke runs, and benchmarks with a wall-clock
timeout:

```bash
timeout --foreground --signal=TERM --kill-after=30s <duration> <command>
```

Suggested limits:

- import/syntax checks: 30 seconds;
- a unit-test file: 120 seconds;
- full unit-test suite: 300 seconds;
- analyzer/inspector: 120 seconds;
- local server readiness: 30 seconds;
- smoke benchmark arm: 600 seconds;
- full 300-500 battle arm: 1,800 seconds.

Always capture and report the exact exit code:

- `0`: success;
- `124`: timeout;
- any other value: failure.

Never assume a command passed merely because it produced no output.

### Long-running Python benchmarks

Implement all three:

1. progress heartbeat every 30 seconds;
2. stall watchdog: fail the arm if finished battle count does not increase for
   180 seconds;
3. total arm timeout using `asyncio.wait_for`.

Heartbeat output must include:

- matchup;
- elapsed seconds;
- finished/planned;
- wins/losses;
- seconds since last completed battle;
- process state if available.

On timeout/stall:

- cancel the battle task;
- close players cleanly where supported;
- mark the arm failed;
- retain partial logs under a filename ending `_partial`;
- do not proceed to the next adoption gate as though the run passed.

The agent must poll running terminal jobs at least once every 60 seconds. It must
not wait for an hour without checking progress.

Immediately after each command:

1. inspect exit code;
2. inspect the last relevant output lines;
3. verify expected artifact exists and is non-empty;
4. report pass/fail before continuing.

## Restrictions

- Local server only.
- Never connect to official Pokemon Showdown.
- No scraping, browser automation, online APIs, or LLM calls during battle.
- Do not use random-set or meta data for abilities.
- Do not infer among multiple possible abilities.
- Do not enable full ability awareness or ability damage multipliers.
- Do not start Phase 6.4.3 or Phase 7.

## Verified Root Cause

`poke-env` loads `Pokemon.possible_abilities` from its local generation Pokédex.
When exactly one ability exists, it also initializes `pokemon.ability` to that
single value.

The bot's `get_known_ability()` currently discards this value for opponents
unless a replay `-ability` event explicitly reveals it. Therefore a species/form
with exactly one legal ability, such as a deterministic Levitate form, is treated
as unknown and Ground moves are not blocked.

## Part 0 - Phase 6.4.2a Report Correction

Do not rerun Phase 6.4.2a battles.

Correct its metrics and documentation using the existing artifacts:

- `interceptions_selected > 0` with `selections_changed = 0` means the feature
  did not cause any observed selection change;
- survival counts in the tens of thousands are invalid because
  `revealed_switch_post_turn_survived=[True, True]` was passed for every slot;
- precision `100%` is misleading when wrong is always zero and most cases are
  unresolved;
- the feature remains rejected/default False.

Change default/unresolved audit values to `None`, not `True` or `False`, where
outcome evidence does not exist. Count survival only for selected interception
events.

Add regression tests for these semantics. Do not present corrected diagnostic
counts as new benchmark results.

## Part 0A - General Dual-Type Mechanics Closure

The reported Ground-into-secondary-Flying case exposes a general requirement:
every move-type calculation must combine both current defender types. Do not
patch only Ground/Flying.

For all move types, use the battle engine's complete dual-type multiplier:

```python
target.damage_multiplier(move)
```

or an equivalent structured type-chart calculation that multiplies the
effectiveness against both `type_1` and `type_2`.

Never calculate final effectiveness from `type_1` alone. Search and correct all
scoring, threat, KO, switch, spread, and audit paths that do this.

Required combined outcomes include:

- immunity: any `0x` component makes the final multiplier `0x`;
- double weakness: `2x * 2x = 4x`;
- double resistance: `0.5x * 0.5x = 0.25x`;
- cancellation: `2x * 0.5x = 1x`;
- ordinary weakness/resistance: `2x` or `0.5x`;
- mono-type behavior remains unchanged.

Examples that must work:

- Electric into Water/Ground = `0x`, not `2x`;
- Electric into Water/Flying = `4x`;
- Fire into Grass/Steel = `4x`;
- Water into Fire/Ground = `4x`;
- Ice into Dragon/Flying = `4x`;
- Fighting into Normal/Ghost = `0x`;
- Psychic into Poison/Dark = `0x`;
- Poison into Grass/Steel = `0x`;
- Dragon into Dragon/Fairy = `0x`;
- Ground into Electric/Flying = `0x`;
- Rock into Fire/Fighting = `1x` due to weakness/resistance cancellation;
- Bug into Grass/Fighting = `1x` due to cancellation;
- Fire into Water/Dragon = `0.25x`.

This applies to current battle typing after transformations or type changes, not
base species typing. Use the current Pokemon object's types.

Do not infer Terastallization or type-changing effects before they occur.

### Ground/Flying Subcase

This remains a specifically audited subcase because it was observed in battle.

Any current target with Flying as either `type_1` or `type_2` is immune to
Ground. Examples:

- Electric/Flying;
- Fire/Flying;
- Water/Flying;
- Steel/Flying.

The bot must not treat Flying immunity as applying only to the primary type.

Use the current complete typing and `target.damage_multiplier(move)`. Do not
infer from species.

Ground may connect only when current reliable state provides an exception:

- move is Thousand Arrows;
- Gravity is active;
- target is under Smack Down;
- target is under Ingrain;
- target is grounded by another battle-engine state that is explicitly and
  reliably represented.

Hidden Iron Ball must not be guessed.

Trace the full scoring path and fix every place that checks only `type_1`,
including threat estimation, zero-effectiveness tie safety, expected damage,
single-target action scoring, spread scoring, and selected-action audit.

Also inspect:

- `estimate_speed_priority_threat`;
- revealed-move incoming risk;
- switch candidate safety;
- expected KO checks;
- HP and focus-fire bonuses;
- threat scoring/tiebreakers even when disabled by default;
- ally-hit calculations;
- benchmark and analyzer classifications.

No KO, HP targeting, focus-fire, threat, or prediction bonus may be added for a
target whose final combined multiplier is zero.

Add selected-action fields:

- `ground_into_flying_selected`
- `ground_into_secondary_flying_selected`
- `ground_into_flying_avoided`
- `ground_into_flying_only_legal`
- `ground_flying_exception_applied`
- `ground_flying_exception_reason`
- target species and both current target types

Separate our bot from opponent baseline actions.

Required tests:

1. every general example listed above returns the exact multiplier;
2. immunity works when the immune type is primary;
3. immunity works when the immune type is secondary;
4. `4x`, `0.25x`, and cancellation-to-`1x` work in either type order;
5. current transformed/type-changed typing is used;
6. expected damage uses the combined multiplier;
7. expected KO is false at `0x`;
8. score is zero at `0x` before joint tie handling;
9. no KO/HP/focus-fire/threat bonus survives a `0x` result;
10. useful legal alternative wins the joint tie;
11. all-immune-only legal actions classify only-legal;
12. partial spread immunity preserves non-immune target damage;
13. all-target immunity scores zero;
14. switch candidate ranking uses full candidate dual typing;
15. revealed-move interception risk uses full dual typing;
16. ally-hit calculations use full ally dual typing;
17. Ground into pure Flying is immune;
18. Ground into Electric/Flying is immune;
19. Ground into Fire/Flying is immune;
20. Ground into Water/Flying is immune;
21. Ground into Flying as `type_1` is immune;
22. Ground into Flying as `type_2` is immune;
23. Thousand Arrows bypasses;
24. Gravity bypasses;
25. Smack Down bypasses;
26. Ingrain bypasses;
27. hidden grounding item is not inferred;
28. audit records current primary and secondary types;
29. opponent Ground-into-Flying is not counted as our error;
30. no species typing is hard-coded in battle decisions.

Add generic audit fields:

- `selected_move_combined_type_multiplier`
- `selected_target_type_1`
- `selected_target_type_2`
- `dual_type_immunity_selected`
- `dual_type_immunity_avoided`
- `dual_type_quad_weakness_targeted`
- `dual_type_double_resistance`
- `dual_type_effectiveness_reason`

Keep selected-action metrics separate from candidate diagnostics and opponent
baseline actions.

Create a reusable diagnostic command:

`inspect_dual_type_mechanics_cases.py`

Filters:

- `--immune`
- `--quad-weak`
- `--quarter-resist`
- `--cancelled-neutral`
- `--secondary-type`
- `--ground-flying`
- `--our-bot`
- `--opponent`
- `--battle`
- `--filepath`

Before smoke benchmark, inspect existing Phase 6.4.1a and Phase 6.4.2a logs and
produce an exhaustive diagnostic count of:

- our Ground into Flying selected;
- our Ground into secondary Flying selected;
- opponent Ground into Flying;
- exception cases;
- repeated streaks by battle and attacker.

Create:

`inspect_ground_into_flying_cases.py`

Filters:

- `--secondary-flying`
- `--our-bot`
- `--opponent`
- `--exception`
- `--only-legal`
- `--battle`
- `--filepath`

The smoke and full benchmark must include these metrics. Adoption is blocked if
our avoidable Ground-into-Flying selection does not approach zero.

## Part 1 - Configuration

Add:

```python
ability_hard_safety_allow_singleton_deduction: bool = False
```

Keep it False until the dedicated benchmark passes.

Do not change:

```python
enable_ability_hard_safety_only = True
enable_ability_awareness = False
ability_hard_safety_avoid_absorb = False
ability_hard_safety_avoid_redirection = False
ability_hard_safety_ally_spread_safety = False
```

## Part 2 - Structured Known Ability Resolution

Create:

```python
def resolve_known_ability(pokemon, battle=None, config=None) -> dict:
    ...
```

Return:

- `ability`: normalized ability or `None`;
- `source`: one of:
  - `our_team_known`
  - `protocol_revealed`
  - `temporary_protocol_change`
  - `deterministic_singleton`
  - `unknown`
- `possible_abilities`: normalized local list;
- `is_deterministic`: bool;
- `is_currently_suppressed`: bool;
- `suppression_reason`: string.

Keep `get_known_ability()` as a compatibility wrapper returning only
`resolution["ability"]`.

Resolution order:

1. our own team's actual known ability;
2. explicit/current protocol ability change or reveal;
3. when the new flag is enabled, a local `possible_abilities` list containing
   exactly one distinct normalized ability;
4. unknown.

For deterministic singleton resolution require:

- exact current species/form object already resolved by poke-env;
- `possible_abilities` exists;
- exactly one distinct non-empty ability;
- `pokemon.ability` is empty or matches that singleton;
- no conflicting protocol ability change exists.

Never:

- select the most likely ability from multiple entries;
- use species usage statistics;
- use random-set data;
- hard-code species-to-ability mappings;
- use an online dex.

## Part 3 - Ability Changes and Suppression

Protocol/current state overrides singleton base data.

Handle reliably represented local mechanics:

- `temporary_ability` from Trace, Skill Swap, Mummy, Wandering Spirit, etc.;
- explicit `-ability` protocol events;
- `-endability`;
- Gastro Acid effect;
- Neutralizing Gas field state;
- Gravity;
- Thousand Arrows;
- Mold Breaker, Teravolt, Turboblaze.

For Levitate, also do not hard-block Ground if a reliable current state shows
that Ground can hit, including Gravity or Smack Down.

Do not guess an unobserved Iron Ball or other hidden item.

If suppression state cannot be determined safely, prefer avoiding the obvious
wasted Ground move; record the uncertainty in audit data.

## Part 4 - Integrate Hard Safety

When:

```python
enable_ability_hard_safety_only=True
ability_hard_safety_allow_singleton_deduction=True
```

allow `ability_hard_blocks_move()` to use a deterministic-singleton resolution.

For Ground into singleton Levitate:

- expected damage = 0;
- expected KO = False;
- action score = block score;
- no KO, HP targeting, focus-fire, or threat bonus;
- guaranteed-waste joint tie safety must prefer a legal useful action;
- spread moves evaluate each target independently;
- if all opponent targets are Levitate-blocked, the spread score is zero;
- partial spread remains usable against non-blocked targets.

Do not activate absorb/redirection/ally features that remain disabled.

## Part 5 - Audit Logging

Add selected-action fields:

- `known_ability_resolution_source`
- `deterministic_singleton_ability_used`
- `deterministic_singleton_ability`
- `deterministic_singleton_target_species`
- `singleton_ability_hard_block_avoided`
- `singleton_ground_into_levitate_selected`
- `singleton_ability_conflict_detected`
- `singleton_ability_suppressed`
- `singleton_ability_suppression_reason`
- `singleton_only_legal_action`

Separate:

- our selected errors;
- our avoided actions;
- opponent baseline actions.

Candidate evaluation must not inflate selected metrics.

## Part 6 - Diagnostic Inspector

Create:

`inspect_singleton_ability_safety_cases.py`

Filters:

- `--singleton-resolved`
- `--levitate`
- `--selected-error`
- `--avoided`
- `--suppressed`
- `--conflict`
- `--only-legal`
- `--our-bot`
- `--opponent`
- `--battle`
- `--filepath`

Print:

- battle, turn, slot;
- attacker, move, target;
- current species/form;
- possible abilities;
- resolved ability and source;
- suppression state;
- selected joint order;
- top five alternatives;
- our-bot/opponent ownership.

## Part 7 - Tests

Add:

`test_doubles_singleton_ability_safety.py`

Required tests:

1. singleton `[levitate]` resolves only when the new flag is enabled;
2. singleton resolution is disabled by default;
3. multiple abilities never resolve by deduction;
4. empty possible abilities remain unknown;
5. exact form's possible abilities are used;
6. no species hard-coded mapping is used;
7. singleton Levitate blocks Ground;
8. singleton Levitate expected damage is zero;
9. singleton Levitate loses a joint zero-score tie to a useful legal action;
10. Thousand Arrows bypasses;
11. Gravity bypasses;
12. Mold Breaker, Teravolt, and Turboblaze bypass;
13. Gastro Acid suppresses;
14. Neutralizing Gas suppresses;
15. Smack Down makes Ground connect;
16. temporary changed ability overrides singleton base ability;
17. explicit protocol reveal overrides singleton base data;
18. conflicting current ability records conflict and does not silently choose;
19. singleton spread partial block preserves the other target;
20. singleton all-target block scores zero;
21. no absorb safety is enabled by this flag;
22. no redirection safety is enabled by this flag;
23. no ally safety is enabled by this flag;
24. selected-action metrics exclude rejected candidates;
25. opponent baseline mistake is not our bot error;
26. Phase 6.4.2 unresolved/survival defaults use `None`;
27. benchmark watchdog detects a stalled arm;
28. benchmark overall timeout cancels and returns exit failure;
29. heartbeat is emitted during a synthetic long task;
30. full suite process terminates naturally.

Run all existing suites plus the new suite with the mandatory timeout wrapper.

## Part 8 - Pre-Benchmark Static Audit

Before running battles:

1. search the local generation Pokédex through poke-env objects;
2. count exact species/forms with a singleton ability;
3. count singleton Levitate forms;
4. print samples;
5. verify no online lookup occurs;
6. verify a multi-ability Levitate-capable species is not treated as
   deterministic unless protocol-revealed.

Save:

`logs/singleton_ability_local_dex_audit.csv`

## Part 9 - Smoke Benchmark

Create:

`bot_doubles_singleton_ability_safety_benchmark.py`

Use the real `DoublesDamageAwarePlayer`, real configs, and audit logger.

Run with watchdogs:

- Off vs Basic: 20;
- On vs Basic: 20;
- On vs Off: 20;
- On vs SafeRandom: 10.

Do not continue if:

- any arm times out or stalls;
- any battle is unfinished;
- On metrics cannot detect deterministic singleton resolution;
- selected/avoided ownership is inconsistent;
- logs are empty;
- analyzer and inspector cannot parse them.

## Part 10 - Full Benchmark

After smoke passes:

- Off vs Basic: 300;
- On vs Basic: 300;
- On vs Off: 300;
- On vs SafeRandom: 100.

Save new Phase 6.3.5 CSV and JSONL artifacts.

Report:

- stability fields;
- singleton resolutions;
- singleton Levitate opportunities;
- hard blocks avoided;
- Ground into singleton Levitate selected;
- only-legal actions;
- protocol-revealed vs singleton resolution counts;
- suppression/bypass counts;
- zero-effectiveness selections;
- Protect, spread, focus-fire;
- win rate and average turns.

## Part 11 - Adoption Gates

Enable `ability_hard_safety_allow_singleton_deduction=True` only if:

- all tests pass and terminate naturally;
- no timeout, stall, crash, exception, or unfinished battle;
- Ground into deterministic singleton Levitate approaches zero except
  only-legal/bypass cases;
- singleton hard blocks are actually observed;
- no multi-ability species is deduced;
- On vs Basic regression is no worse than -2 percentage points;
- On vs Off is at least 50%;
- On vs SafeRandom is at least 95%;
- spread and focus-fire do not collapse.

If any gate fails, preserve code/tests/artifacts and keep the flag False.

## Part 12 - Documentation

Update `walkthrough.md` with:

- why revealed-only missed deterministic singleton Levitate;
- distinction between deterministic singleton deduction and probabilistic
  species inference;
- local-only data source;
- ability-change/suppression handling;
- timeout/heartbeat/stall policy;
- exact tests, exit codes, smoke and full benchmark rows;
- corrected Phase 6.4.2a metric interpretation;
- adoption decision and exact defaults;
- Phase 6.4.3 and Phase 7 remain unstarted.

## Final Report

Return:

1. changed files;
2. exact watchdog settings and any timeout/stall incidents;
3. full tests, exit codes, durations, and natural termination;
4. local singleton dex audit;
5. smoke results;
6. full benchmark rows;
7. singleton Levitate safety metrics;
8. protocol-revealed vs singleton resolution metrics;
9. adoption decision and exact defaults;
10. confirmation that full ability awareness, probabilistic multi-ability
    inference, official server, Phase 6.4.3, and Phase 7 were not used.
