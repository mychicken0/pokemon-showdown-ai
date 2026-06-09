# Phase 6.3.5a - Singleton Ability and Priority Field Correction

This is a correction phase for Antigravity. Do not trust the previous Phase
6.3.5 singleton audit or adoption decision until this plan is complete.

## Confirmed Evidence

Local `poke-env` Gen 9 data contains:

```text
cresselia {'0': 'Levitate'}
rotom     {'0': 'Levitate'}
flygon    {'0': 'Levitate'}
mismagius {'0': 'Levitate'}
```

The previous inspector iterated the ability dictionary itself:

```python
for ab in abilities:
```

This reads keys such as `"0"` instead of values such as `"Levitate"`. Its report
of zero singleton Levitate forms is invalid.

The screenshot battle was played by `Sin635_Off_Bas...`, the explicit Off arm.
Ground into unrevealed Cresselia Levitate is therefore expected in that arm and
does not prove the On implementation failed. The On arm must now be tested with
correct metrics.

The user also observed Sucker Punch/priority moves being selected into Psychic
Terrain. This is a separate hard field-mechanics issue.

## Mandatory Command Watchdogs

Every command must use:

```bash
timeout --foreground --signal=TERM --kill-after=30s <limit> <command>
```

Limits:

- static/import checks: 30 seconds;
- individual tests: 120 seconds;
- full suite: 300 seconds;
- analyzers: 120 seconds;
- smoke arm: 600 seconds;
- full arm: 1800 seconds.

For benchmark Python:

- heartbeat every 30 seconds;
- poll running jobs at least every 60 seconds;
- stall failure after 180 seconds without a completed battle;
- `asyncio.wait_for` total arm timeout;
- cancel and close players on timeout/stall;
- partial logs end in `_partial`;
- timeout/stall is a failed run, never a pass.

After every command:

1. report exact exit code;
2. inspect final output;
3. verify expected artifact exists and is non-empty;
4. state pass/fail before continuing.

## Restrictions

- Local server only.
- No official server, web scraping, browser automation, online APIs, or battle
  LLM calls.
- No inference among multiple possible abilities.
- No random-set or meta ability prediction.
- Keep full ability awareness disabled.
- Do not start Phase 6.4.3 or Phase 7.

## Part 1 - Correct Local Ability Extraction

Create one reusable helper:

```python
def normalize_possible_abilities(raw) -> list[str]:
    ...
```

Rules:

- if `raw` is a dict, iterate `raw.values()`;
- if `raw` is a list/tuple/set, iterate its values;
- normalize and deduplicate;
- skip empty values;
- deterministic order for reports;
- never interpret slot keys `"0"`, `"1"`, or `"H"` as abilities.

Use this helper in:

- `resolve_known_ability()`;
- `inspect_singleton_ability_local_dex.py`;
- tests;
- benchmark diagnostics;
- any other singleton counting path.

The static audit must print and save all singleton Levitate forms, not only the
first twenty.

Add explicit assertions:

- Cresselia resolves to singleton Levitate with feature On;
- Rotom base form resolves to singleton Levitate;
- Flygon resolves to singleton Levitate;
- Mismagius resolves to singleton Levitate;
- Weezing does not resolve because it has multiple abilities;
- Bronzong does not resolve because it has multiple abilities.

## Part 2 - Verify Runtime Opponent Objects

Add a local diagnostic script:

`inspect_runtime_singleton_ability_state.py`

For selected local audit battles or a small controlled battle, print:

- battle tag and turn;
- opponent species/form;
- `pokemon.ability`;
- `pokemon.temporary_ability`;
- raw `pokemon.possible_abilities`;
- normalized possible abilities;
- resolver output and source;
- singleton flag state;
- whether Ground would be blocked.

Support:

- `--species`
- `--battle`
- `--filepath`

Do not rely only on mock objects.

## Part 3 - Singleton Levitate Scoring Integration

With:

```python
enable_ability_hard_safety_only=True
ability_hard_safety_allow_singleton_deduction=True
```

verify the complete real-player path:

- `get_expected_damage()` returns zero;
- `check_move_will_ko()` returns false;
- `score_action()` returns block score;
- no KO/HP/focus-fire/threat bonus survives;
- joint selection prefers a useful legal action;
- selected-action audit records deterministic-singleton source;
- spread evaluates each target separately.

Exceptions remain:

- Gravity;
- Thousand Arrows;
- Mold Breaker;
- Teravolt;
- Turboblaze;
- reliable Smack Down/Ingrain/grounding state.

Do not infer hidden Iron Ball.

## Part 4 - Psychic Terrain Priority Hard Safety

Add:

```python
def priority_move_is_field_blocked(
    move,
    attacker,
    target,
    battle,
) -> tuple[bool, str]:
    ...
```

Use current battle state only.

Psychic Terrain rule:

- if move priority is greater than zero;
- move targets an opposing Pokemon;
- Psychic Terrain is active;
- intended target is grounded according to `battle.is_grounded(target)`;
- the move is blocked and should score zero.

Important:

- Flying targets are not grounded unless a reliable grounding effect applies;
- Levitate targets are not grounded unless Gravity/Smack Down/etc. applies;
- grounded status must use current types/effects, not base species;
- Psychic Terrain does not block a priority move targeting an ungrounded
  opponent;
- do not apply this rule to self/ally/field moves;
- do not apply it merely because Sucker Punch is conditional.

For Sucker Punch specifically:

- under Psychic Terrain against a grounded opponent, score and expected damage
  are zero;
- no KO bonus or focus-fire bonus;
- useful legal alternatives win ties;
- outside Psychic Terrain, preserve existing conditional-priority behavior.

Also implement known hard priority blockers when reliably known:

- Armor Tail;
- Queenly Majesty;
- Dazzling.

These abilities protect their side from opposing priority. Use only
protocol-revealed or deterministic-singleton resolution. Do not enable general
ability scoring.

## Part 5 - General Priority Legality Helper

Create a structured helper:

```python
def evaluate_priority_move_legality(
    move,
    attacker,
    intended_target,
    battle,
    config=None,
) -> dict:
    ...
```

Return:

- priority;
- is priority move;
- intended target grounded;
- Psychic Terrain active;
- known side-blocking ability;
- blocked;
- reason;
- resolution source.

Integrate into:

- expected damage;
- expected KO;
- single-target score;
- joint tie safety;
- speed/priority threat analysis;
- selected-action audit.

If blocked, do not add any damage-related bonus.

## Part 6 - Audit and Inspectors

Add selected-action fields:

- `priority_move_field_blocked`
- `priority_move_block_reason`
- `priority_move_selected_into_psychic_terrain`
- `sucker_punch_selected_into_psychic_terrain`
- `priority_move_block_avoided`
- `priority_move_only_legal`
- `priority_target_grounded`
- `priority_target_species`
- `priority_target_type_1`
- `priority_target_type_2`
- `priority_blocking_ability`
- `priority_blocking_ability_source`

Separate our bot from opponent baseline actions.

Create:

`inspect_priority_field_block_cases.py`

Filters:

- `--psychic-terrain`
- `--sucker-punch`
- `--ability-block`
- `--selected-error`
- `--avoided`
- `--only-legal`
- `--grounded`
- `--ungrounded`
- `--our-bot`
- `--opponent`
- `--battle`
- `--filepath`

## Part 7 - Tests

Create/update focused tests covering:

### Singleton ability

1. dict ability values are parsed, not keys;
2. Cresselia singleton Levitate resolves On;
3. Cresselia remains unknown Off before reveal;
4. protocol reveal works in both modes;
5. multi-ability Weezing and Bronzong are not deduced;
6. real player avoids Ground into singleton Cresselia On;
7. Off control may select it before reveal;
8. audit source is deterministic singleton;
9. candidate metrics do not inflate selected metrics.

### Psychic Terrain

10. Sucker Punch into grounded target is blocked;
11. Quick Attack into grounded target is blocked;
12. Fake Out into grounded target is blocked;
13. priority damaging move expected damage is zero;
14. expected KO is false;
15. no KO/HP/focus-fire bonus survives;
16. non-priority move remains valid;
17. Sucker Punch into Flying target remains valid;
18. Sucker Punch into Levitate target remains valid;
19. Gravity makes a Flying/Levitate target grounded and therefore blocked;
20. Smack Down grounding causes Psychic Terrain block;
21. self/ally priority is not incorrectly blocked;
22. useful legal alternative wins the joint tie;
23. all-priority-only legal actions classify only-legal;
24. Armor Tail blocks priority against either opponent slot;
25. Queenly Majesty blocks priority;
26. Dazzling blocks priority;
27. unknown/multiple ability is not guessed;
28. opponent mistake is not our error.

### Existing mechanics

29. all general dual-type multiplier tests remain exact;
30. Ground into secondary Flying remains blocked;
31. full suite terminates naturally under timeout.

Run every existing suite, not only new tests.

## Part 8 - Correct Phase 6.3.5 Artifacts

Mark the previous local singleton dex audit and Phase 6.3.5 adoption conclusion
invalid due to dictionary-key iteration.

Do not overwrite the old files. Produce corrected files containing `phase635a`.

Corrected static audit must include:

- total exact species/forms;
- singleton count;
- singleton Levitate count;
- complete singleton Levitate species/form list;
- multi-ability Levitate count and list.

## Part 9 - Smoke Qualification

Use real bot/config/audit logger.

Run:

- singleton Off vs Basic: 20;
- singleton On vs Basic: 20;
- singleton On vs Off: 20;
- singleton On vs SafeRandom: 10.

Additionally run controlled local scenario tests where practical:

- Gliscor with High Horsepower vs Cresselia plus a useful alternative;
- Sucker Punch user vs grounded target under Psychic Terrain;
- Sucker Punch user vs Flying target under Psychic Terrain.

Smoke must show:

- singleton Cresselia opportunities exist;
- On blocks/avoids them;
- Off remains a valid control;
- Psychic Terrain selected errors approach zero;
- no timeout/stall.

## Part 10 - Full Qualification

After smoke passes:

- Off vs Basic: 300;
- On vs Basic: 300;
- On vs Off: 300;
- On vs SafeRandom: 100.

Report:

- Cresselia/Rotom/Flygon/Mismagius singleton resolutions;
- Ground into singleton Levitate selected/avoided/only-legal;
- protocol vs singleton resolution;
- Psychic Terrain priority opportunities;
- Sucker Punch selected errors;
- priority blocks avoided;
- grounded vs ungrounded cases;
- Armor Tail/Queenly Majesty/Dazzling cases;
- general dual-type and Ground/Flying metrics;
- stability, win rate, Protect, spread, focus-fire.

## Part 11 - Adoption

Evaluate two defaults independently:

1. `ability_hard_safety_allow_singleton_deduction`
2. a new `enable_priority_field_hard_safety`

Each defaults False until its own gates pass.

Priority field hard safety may be adopted independently if:

- tests pass;
- selected avoidable priority-into-Psychic-Terrain approaches zero;
- On vs Basic regression no worse than -2 pp;
- On vs Off >= 50%;
- On vs SafeRandom >= 95%;
- no behavioral collapse.

Singleton deduction may be adopted only with corrected singleton opportunities,
actual blocks, and the same performance/stability gates.

## Part 12 - Documentation

Correct `walkthrough.md`:

- screenshot was from the explicit Off arm;
- previous singleton audit read dict keys and was invalid;
- local dex proves Cresselia/Rotom/Flygon/Mismagius singleton Levitate;
- corrected tests/audit/benchmark;
- Psychic Terrain grounded-target priority mechanics;
- Sucker Punch behavior;
- watchdog execution policy;
- separate adoption decisions and exact defaults;
- Phase 6.4.3 and Phase 7 remain unstarted.

## Final Report

Return:

1. changed files;
2. timeout/heartbeat/stall settings and incidents;
3. corrected singleton dex audit;
4. full test count, duration, exit code, natural termination;
5. controlled scenario results;
6. smoke rows;
7. full benchmark rows;
8. singleton Levitate safety metrics;
9. Psychic Terrain/Sucker Punch safety metrics;
10. separate adoption decisions and exact defaults;
11. confirmation that no hidden multi-ability inference, full ability awareness,
    official server, Phase 6.4.3, or Phase 7 was used.
