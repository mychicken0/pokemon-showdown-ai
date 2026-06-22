# Phase 6.4.2a - Integration Repair and Qualification

Do not run the 1,600-battle Phase 6.4.2 benchmark yet. The current implementation
does not instantiate or exercise the real bot and cannot produce valid audit
metrics.

## Restrictions

- Keep all work local-only.
- Do not connect to official Pokemon Showdown.
- No scraping, browser automation, online APIs, or LLM calls in battle.
- No hidden move/item/ability inference.
- Keep full ability, meta, and random-set awareness disabled.
- Do not start Phase 6.4.3 or Phase 7.

## Codex Review Findings

The following are verified blockers, not pre-existing issues:

1. `class DoublesDamageAwarePlayer(Player):` is missing. The existing
   `__init__`, `score_action`, `choose_move`, and other player methods are
   currently nested inside `evaluate_revealed_move_switch_interception()` after
   its `return`. Five established test modules fail to import the player.
2. The 41 new tests pass because they test helpers/config with mocks and do not
   instantiate the real player.
3. The switch branch in `score_action()` references `valid_orders`,
   `slot_0_scores`, and `slot_1_scores`. Those variables exist only inside
   `choose_move()`. Enabling the feature would raise `NameError`.
4. `bot_doubles_revealed_move_switch_interception_benchmark.py` creates a random
   base `Player`, ignores the supplied config and audit logger, and never creates
   `DoublesDamageAwarePlayer`.
5. Its `On vs Off` arm actually uses Basic as the opponent.
6. Phase 6.4.2 audit parameters were added to
   `DoublesDecisionAuditLogger.log_turn_decision()`, but the real player never
   passes them. They therefore remain default false/empty.
7. No local-event resolution currently sets predicted move used, prediction
   correct/wrong, post-switch damage, survival, or candidate fainted.
8. Several required tests are placeholders:
   - feature-Off test does not compare scores;
   - zero-score tie test does not run joint selection;
   - outcome-evidence test is `assertTrue(True)`;
   - Water into Fire/Ground uses a pure Ground target and accepts `2x`;
   - the named Electric/Ground test first tests Electric/Steel.
9. Move-action gating indexes opponent slots without checking
   `move_target in (1, 2)`, so spread/self/ally targets may use the wrong target.
10. The combined test process did not terminate cleanly after the import
    failures, indicating leaked runtime resources that must be checked.

## Part 1 - Restore the Player Class

Restore:

```python
class DoublesDamageAwarePlayer(Player):
```

immediately before the existing indented `__init__`.

Requirements:

- all original player methods must be class members again;
- Phase 6.4.2 helpers remain top-level pure functions;
- importing the module must not create players, tasks, sockets, or threads;
- verify:

```python
from bot_doubles_damage_aware import DoublesDamageAwarePlayer
assert issubclass(DoublesDamageAwarePlayer, Player)
assert hasattr(DoublesDamageAwarePlayer, "score_action")
assert hasattr(DoublesDamageAwarePlayer, "choose_move")
```

Add a structural regression test so removal of the class declaration cannot
pass again.

## Part 2 - Move Interception Scoring Out of `score_action`

Remove Phase 6.4.2 logic that depends on `valid_orders` or slot score maps from
`score_action()`.

Integrate it in `choose_move()` after canonical per-slot base scores are
calculated:

1. retain immutable legacy slot scores;
2. inspect legal switch orders for each non-forced live slot;
3. calculate its best genuine legal move/action score from canonical scores;
4. calculate expected KO/high-value gates with valid targets only;
5. calculate the switch interception bonus;
6. add the bonus to the switch order's experimental score;
7. build complete legal joint orders from the adjusted slot scores;
8. retain a complete legacy best joint order for counterfactual comparison.

Do not recursively call `score_action()` to obtain the same scores.

For KO checks:

- only dereference an opponent when `move_target in (1, 2)`;
- handle spread moves separately;
- ignore self, ally, field, and pass targets;
- do not treat malformed target metadata as a KO.

The feature must not affect scores when disabled.

## Part 3 - Real Joint Counterfactual

Calculate:

- legacy best legal joint order with the feature Off;
- enabled best legal joint order with interception bonuses;
- deterministic selection-change boolean;
- per-slot changed action;
- changed-to-switch boolean.

The counterfactual must include all existing synergy and safety adjustments in
both paths. Only the Phase 6.4.2 bonus may differ.

Do not report `selection_changed=True` merely because two equivalent order
objects have different identities.

## Part 4 - Wire Selected Audit Fields

Create selected-action lists in `choose_move()` and pass every Phase 6.4.2 field
to `audit_logger.log_turn_decision()`.

Candidate-level evaluation must not inflate selected metrics.

Definitions:

- `prediction_available`: at least one legal switch candidate has a valid
  revealed-move interception for this selected decision event.
- `interception_selected`: final selected action is that validated switch.
- `selection_changed`: legacy selected a different action and enabled selected
  the interception switch.
- blocked/rejected metrics are diagnostic candidate counters and must be
  reported separately from selected-action counts.

Add an audit schema test that uses a real `DoublesDamageAwarePlayer` mock battle,
runs `choose_move()`, writes one JSONL record, and verifies non-default values.

## Part 5 - Resolve Outcomes From Local Events

Implement outcome resolution in `DoublesDecisionAuditLogger.update_previous_turn`
or a narrowly scoped helper called from it.

Track the switched-in Pokemon by identity, not species alone when possible.

For a selected interception:

- inspect local protocol events for opponent move usage;
- normalize move IDs consistently;
- determine whether one of the predicted revealed moves was used;
- determine whether the move targeted or affected the intercepted slot when
  protocol data makes this reliable;
- calculate HP before and after from battle/event data;
- record damage taken;
- record survived/fainted;
- set correct/wrong only when evidence is sufficient.

Use three-state semantics internally:

- correct;
- wrong;
- unknown/unresolved.

Do not coerce unknown to wrong or survived by default. JSON fields that are
unknown should be `null`, not optimistic `True`.

Add tests with synthetic local protocol event sequences for:

- predicted single-target move hits switched-in Pokemon;
- predicted move used on partner instead;
- predicted spread move affects switched-in Pokemon;
- opponent uses a different revealed move;
- no opponent move event;
- switched-in Pokemon faints;
- duplicate species identities.

## Part 6 - Correct Type-Immunity Audit

The zero-effectiveness joint tie rule must remain, but add real integration
tests.

Audit:

- final selected immune action;
- only-legal immune action;
- immune action avoided relative to the legacy tie selection;
- opponent immune action observed from protocol events.

Do not store `opponent_type_immune_move_selected` as a per-our-slot value. It is
an opponent action/event metric and should live under `opp_actions` or another
explicit opponent structure.

Add exact real-selection tests:

1. immune damaging move and legal status move both score zero: status wins;
2. immune damaging move and legal non-immune damaging move: non-immune wins;
3. every legal move immune: selected is classified only-legal;
4. partial spread immunity remains selectable;
5. opponent Electric into Electric/Ground is opponent-only;
6. our Electric into Electric/Ground is blocked and not selected when an
   alternative exists.

## Part 7 - Replace Placeholder Tests

The Phase 6.4.2 suite must instantiate a lightweight subclass of the real player
using the established test pattern from existing suites.

Replace all structural/placeholding assertions with behavioral assertions.

Correct dual-type fixtures:

- Electric into Electric/Ground exactly `0.0`;
- Water into Fire/Ground exactly `4.0`;
- Ground into Electric/Flying exactly `0.0`;
- Fire into Grass/Steel exactly `4.0`;
- Electric into Water/Flying exactly `4.0`.

Test feature-Off by comparing complete selected joint order and all canonical
scores against a control config.

Test feature-On with:

- a revealed Fire move;
- Grass active;
- Water switch candidate;
- no high-value action;
- selected action changes to the Water switch.

Test the inverse gates:

- unrevealed Fire move causes no change;
- immediate KO preserves attack;
- dangerous second opponent rejects candidate;
- forced switch gets no interception bonus.

## Part 8 - Repair the Benchmark

Rewrite `bot_doubles_revealed_move_switch_interception_benchmark.py` using the
working Phase 6.4.1a benchmark structure.

It must instantiate:

- primary: `DoublesDamageAwarePlayer(config=...)`;
- Basic opponent for Basic arms;
- `DoublesDamageAwarePlayer(config_off)` for On vs Off;
- SafeRandom opponent for SafeRandom arm;
- a real audit logger attached to the primary player.

Do not subclass random `Player`.

Use `await player.battle_against(opponent, n_battles=n)` once per arm and read
finished/win counts from player state, matching existing working benchmarks.

Required CSV fields:

- planned, finished, unfinished;
- wins, losses, ties, win rate, average turns;
- crashes, exceptions, timeouts;
- all Phase 6.4.2 prediction metrics;
- correct, wrong, unresolved;
- prediction precision denominator;
- post-interception survival/faint counts;
- voluntary/forced switches;
- our/opponent type-immunity errors;
- Protect, spread, focus-fire, KO conversion;
- all-target immune and partial-spread counts.

Validate CSV values against JSONL recomputation before accepting each row.

## Part 9 - Full Verification Before Server Benchmark

Run:

```bash
venv/bin/python -m unittest \
  test_doubles_revealed_move_switch_interception.py \
  test_doubles_switch_candidate_safety.py \
  test_doubles_ability_hard_safety.py \
  test_doubles_mechanics_scoring.py \
  test_doubles_speed_priority.py \
  test_doubles_speed_priority_analysis.py
```

Requirements:

- zero import errors;
- zero failures;
- process exits naturally with code 0;
- no leaked process, thread, socket, or asyncio task;
- test count must include all established tests, not only the 41 new tests.

Do not start the battle benchmark unless this gate passes.

## Part 10 - Local Smoke Qualification

With the local server running, run four smoke arms first:

- Off vs Basic: 20
- On vs Basic: 20
- On vs Off: 20
- On vs SafeRandom: 10

Verify:

- all finish;
- On uses `DoublesDamageAwarePlayer`;
- nonzero prediction availability appears when revealed threats occur;
- selected/correct/wrong/unresolved fields are populated coherently;
- Off has zero applied interception bonuses;
- On vs Off identities/configs are correct;
- JSONL is non-empty and analyzer/inspector can parse it;
- no official server connection is configured.

If no selection changes occur in smoke despite predictions, inspect scoring and
do not proceed blindly.

## Part 11 - Full Qualification

Only after Parts 1-10 pass, run:

- Off vs Basic: 500
- On vs Basic: 500
- On vs Off: 500
- On vs SafeRandom: 100

Use new `phase642a` filenames. Do not overwrite invalid or preliminary Phase
6.4.2 artifacts.

Apply the original Phase 6.4.2 adoption gates, including SafeRandom >=95% and
prediction precision >=55%.

Keep `enable_revealed_move_switch_interception=False` unless every gate passes.

## Part 12 - Documentation

Correct `walkthrough.md` to state:

- the initial Phase 6.4.2 implementation was rejected before benchmark;
- the player class declaration was accidentally removed;
- existing suites failed import;
- the initial benchmark script used random play and ignored config/audit;
- the 41-test result was helper-only and insufficient;
- exact repaired full-suite result;
- smoke and full benchmark results;
- exact adoption decision/defaults;
- Phase 6.4.3 and Phase 7 remain unstarted.

## Final Report

Return:

1. changed files;
2. restored class/integration details;
3. full test count, exit code, and clean process termination;
4. smoke results;
5. four full benchmark rows;
6. prediction selected/correct/wrong/unresolved/survival metrics;
7. our vs opponent type-immunity metrics;
8. artifact consistency verification;
9. adoption decision and exact defaults;
10. confirmation that Phase 6.4.3 and Phase 7 were not started.
