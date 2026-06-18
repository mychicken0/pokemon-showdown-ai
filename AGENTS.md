# Pokémon Showdown AI Agent Guide

This file defines the operating rules for any coding agent working in this
repository. Follow it before reading old reports or starting implementation.

## Project Scope

This repository contains a local-only Pokémon Showdown AI bot built with
`poke-env`.

- AI project: `/home/phurin/Program/Showdown_AI/pokemon-showdown-ai`
- Local server: `/home/phurin/Program/Showdown_AI/pokemon-showdown`
- Main doubles player: `bot_doubles_damage_aware.py`
- Main format: `gen9randomdoublesbattle`
- Decision audit log: `logs/doubles_decision_audit.jsonl`
- Development history and qualification results: `walkthrough.md`

The current development line is Phase 6. Do not start Phase 7 unless the user
explicitly authorizes it.

## Non-Negotiable Restrictions

Everything must remain local.

- Connect only to the local Pokémon Showdown server, normally
  `localhost:8000`.
- Never connect to the official Pokémon Showdown server.
- Never scrape websites.
- Never use browser automation.
- Never call online APIs during battle decisions.
- Never call an LLM during battle decisions.
- Never download battle data, sets, usage statistics, or model outputs during a
  battle.
- Do not expose a server started with `--no-security` to the public network.
- Do not infer hidden moves, held items, or probabilistic abilities from a
  species.
- Do not enable full ability awareness.
- Do not enable meta or random-set opponent prediction by default.

An approved narrow exception exists for deterministic singleton abilities when
`ability_hard_safety_allow_singleton_deduction=True`. It may use only local
dex data proving exactly one legal ability. It must never guess between
multiple abilities.

## Current Configuration Direction

The source code is authoritative. Verify values in
`DoublesDamageAwareConfig` before reporting them.

Expected adopted defaults include:

```python
enable_type_immunity_safety = True
enable_self_drop_move_penalty = True
enable_partial_spread_immunity_penalty = True
enable_speed_priority_awareness = True
speed_priority_protect_only = False
enable_order_aware_overkill = False

enable_ability_hard_safety_only = True
ability_hard_safety_block_score = 0.0
ability_hard_safety_direct_absorb_only = True
ability_hard_safety_allow_singleton_deduction = True
ability_hard_safety_avoid_absorb = False
ability_hard_safety_avoid_redirection = False
ability_hard_safety_ally_spread_safety = False

enable_priority_field_hard_safety = False
enable_known_ally_redirection_hard_safety = False
enable_switch_candidate_type_safety = False
enable_revealed_move_switch_interception = False
enable_forced_switch_replacement_safety = False
enable_stale_target_after_ally_ko_safety = False
enable_stat_drop_switch_scoring = False
enable_decision_timing_diagnostics = False

enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
enable_threat_tiebreaker = False
```

`enable_stat_drop_switch_diagnostics=True` is observational only. It must not
change scoring.

Phase 6.3.8 support-move target safety is under development and must remain
disabled until its adoption gates pass:

```python
enable_support_move_target_hard_safety = False
```

Do not change any default merely because a helper or test exists.

## Information Integrity

Battle decisions may use only information legitimately available at that
decision.

Allowed:

- Visible Pokémon types and HP.
- Our own team, moves, abilities, items, and boosts.
- Opponent moves, abilities, forms, and effects explicitly revealed by the
  protocol.
- Current field, weather, terrain, side conditions, and visible boosts.
- Deterministic singleton ability resolution under the approved flag.

Forbidden:

- Reading possible opponent moves and treating them as known.
- Inferring an ability from species when multiple abilities are possible.
- Random-set or usage data as hidden-state evidence.
- Looking at future replay events.
- Reclassifying post-turn reveals as knowledge available before the decision.

Audit fields must distinguish:

- known before decision,
- revealed after decision,
- deterministic singleton deduction,
- our bot error,
- opponent observational error.

## Mechanics Rules

### Types

- Evaluate the complete dual-type multiplier, not each type independently.
- Any type immunity makes expected damage zero unless a real mechanics
  exception applies.
- Preserve exceptions such as Gravity, Thousand Arrows, Scrappy, and
  Mind's Eye where implemented and tested.
- Dynamic move types must use observable protocol form state. Aura Wheel is
  Electric in Full Belly form and Dark in Hangry form.

### Abilities

- Hard safety uses known/revealed abilities, plus the approved deterministic
  singleton exception.
- Do not add speculative damage multipliers such as Fluffy, Thick Fat,
  Multiscale, Ice Scales, or Punk Rock under hard-safety-only mode.
- Mold Breaker, Teravolt, and Turboblaze bypass only when the attacker's
  ability is known.

### Blocked Actions

When a target is immune or an action is hard-safety blocked:

- expected damage is `0`,
- expected KO is `False`,
- do not add KO, low-HP, focus-fire, threat, spread, or support synergy bonuses,
- ensure joint-order scoring cannot resurrect the blocked action,
- evaluate each spread target independently,
- preserve useful damage to non-immune spread targets.

### Switches

Forced replacement, voluntary switching, revealed-move interception, and
stat-drop switching are separate features. Do not enable one as a side effect
of another.

## Working Method

### 1. Read Before Editing

Before changing behavior:

1. Inspect `DoublesDamageAwareConfig`.
2. Trace the real production path from `choose_move()` to scoring and final
   joint selection.
3. Inspect the logger, analyzer, inspector, tests, and existing artifacts for
   the feature.
4. Reproduce or classify the reported battle case.
5. Identify whether the defect is in mechanics, scoring, joint scoring,
   selection, audit logging, or report aggregation.

Do not assume that an audit value proves scoring behavior. Audit code has had
independent defects in the past.

### 2. Keep Changes Narrow

- Prefer existing helpers and scoring patterns.
- Use pure helpers for classification and accounting.
- Keep diagnostics observational unless the phase explicitly authorizes
  scoring.
- Avoid unrelated refactors in `bot_doubles_damage_aware.py`.
- Do not delete old benchmark artifacts.
- Do not overwrite artifacts without an explicit `--overwrite` option.

### 3. Preserve User Work

The worktree may be dirty.

- Never revert changes you did not make.
- Never use `git reset --hard` or destructive checkout commands.
- Inspect overlapping edits and work with them.
- Do not commit or push unless the user explicitly requests it.

## Tests

Run Python from the project virtual environment:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown-ai
source venv/bin/activate
```

Every command must have a foreground timeout. Examples:

```bash
timeout --foreground --signal=TERM --kill-after=10s 300s \
  ./venv/bin/python -W error::ResourceWarning -m unittest \
  test_doubles_support_move_target_safety.py
```

Full maintained suite:

```bash
/usr/bin/time -f 'EXIT=%x ELAPSED=%e' \
  timeout --foreground --signal=TERM --kill-after=10s 300s \
  ./venv/bin/python -W error::ResourceWarning -m unittest
```

The last Codex-verified baseline before Phase 6.3.8 was 709 passing tests.
This count is historical, not a fixed acceptance value. Report the actual
current count and exit code.

### Test Quality

- Test production helpers and production scoring paths.
- Prefer real `Move`, `Pokemon`, battle, and order semantics.
- Avoid assertions that only inspect source text when behavior can be tested.
- Never use placeholder assertions such as `assertTrue(True)` or
  `assertFalse(False)`.
- Avoid semantically impossible fixtures.
- Include positive, negative, exception, accounting, and regression cases.
- Run tests with `-W error::ResourceWarning`.

### Evidence Ladder

Do not use large battle samples to debug logic. Use the smallest evidence that
can answer the question.

Use this order for new mechanics, scoring, switching, learned policies, audit
fields, and runner changes:

1. **Fixture/unit test for logic.**
   - Arrange the exact battle state, active Pokemon, legal orders, HP,
     flags, scores, and audit inputs.
   - Assert the exact generated orders, scores, selected action, blocked
     action, or serialized audit field.
   - This is the correct tool for questions like "does Mega get generated",
     "does a status move avoid the Mega bonus", "does a low-HP switch candidate
     beat staying in", or "does default OFF strip all Mega orders".

2. **Targeted runtime probe for integration.**
   - Use one battle or one pair only when the question involves poke-env,
     Showdown protocol, runner wiring, side/perspective labels, or persisted
     audit artifacts.
   - This is the correct tool for questions like "does Showdown expose
     `can_mega_evolve`", "does the runner attach the audit logger", or
     "does the persisted JSONL contain the expected field".
   - Do not interpret this as strength evidence.

3. **Small smoke for regression shape.**
   - Use roughly 5-20 pairs to check for crashes, timeouts, spam, missing audit
     fields, side collapse, or obviously broken behavior after logic and
     integration already pass.
   - This is not an adoption gate.

4. **Preview sample for directional signal.**
   - Use moderate samples only after fixture tests and targeted probes prove
     the feature is actually exercising the intended path.
   - Treat the result as a signal to continue, defer, or redesign. Do not flip
     defaults from a preview.

5. **Full qualification for adoption.**
   - Use large paired benchmarks only when deciding whether to adopt or flip a
     default.
   - Never run a 100/200-pair benchmark to discover that a flag, audit field,
     order generator, side mapping, or baseline arm is wired incorrectly.

If logic is not fixture-tested, do not proceed to a large benchmark. If runtime
integration is not proven with a targeted probe, do not proceed to a smoke or
qualification. If audit/accounting is inconsistent, stop and fix the accounting
before interpreting win rates.

When the user asks for speed, reduce sample size and improve targeting; do not
skip the earlier evidence layers.

### poke-env Test Lifecycle

`Player.__init__` can create background `POKE_LOOP` resources.

- Construct lightweight unit-test players with `__new__` when full networking
  is unnecessary.
- Use the repository's `poke_env_test_cleanup` pattern in test modules.
- Verify combined suites terminate naturally.
- Do not hide leaks by relying only on timeout termination.

## Local Server

Start only the local server:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown
./pokemon-showdown start --no-security
```

Repo helper:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown-ai
./scripts/start_local_showdown.sh
```

Use the `pokemon-showdown` executable wrapper, not
`node pokemon-showdown start --no-security`. In Codex/OpenCode tool sessions,
run it as a long-running foreground session; `nohup`/detached launches have
been observed to exit immediately without keeping port 8000 open.

Health check:

```bash
timeout --foreground --signal=TERM --kill-after=2s 5s \
  curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000
```

Expected result: `200`.

If port 8000 is already active, verify it before starting another process.
Do not kill an existing server blindly.

## Long-Running Battle Jobs

Never launch a benchmark and wait indefinitely.

Every runner must provide:

- periodic heartbeat output,
- a stall timeout,
- a per-arm timeout,
- an outer shell timeout,
- clean cancellation and player shutdown,
- non-zero exit status for timeout, stall, crash, validation failure, or
  insufficient valid evidence.

Recommended defaults:

```text
heartbeat: 30 seconds
stall timeout: 180 seconds
arm timeout: based on planned battle count
outer shell timeout: longer than the internal arm total
```

For targeted runs, shorter values are appropriate, such as 10-second
heartbeats and a 60-second stall timeout.

Poll background jobs after launch. A scheduled timer is not a substitute for
checking the process and its output.

## Qualification Order

Use this sequence:

1. Static/import/compile checks.
2. Focused unit tests.
3. Full maintained unit-test suite.
4. Deterministic targeted qualification proving the exact mechanism.
5. Small smoke benchmark.
6. Full benchmark only when smoke evidence is valid.
7. Artifact validation.
8. Adoption decision.
9. Documentation update.

Do not run a large benchmark to discover that instrumentation or accounting is
wrong.

## Benchmark Design

Use explicit control and treatment arms. Typical doubles qualification:

- feature OFF vs Basic,
- feature ON vs Basic,
- feature ON vs feature OFF,
- feature ON vs SafeRandom.

Requirements:

- unique artifact tag,
- no overwrite by default,
- local server metadata recorded,
- planned and finished battle counts,
- wins, losses, ties/unknown,
- crashes, exceptions, stalls, and timeouts,
- average turns,
- relevant behavior counters,
- spread and focus-fire usage,
- exact config flags for every arm.

Random battle win-rate changes do not prove causality unless the feature
actually changed selections.

## Artifact Validation

Validate JSONL and CSV before reporting:

- expected record count,
- unique battle tags,
- valid boolean outcomes,
- correct benchmark arm metadata,
- no malformed JSON,
- planned count equals finished count,
- accounting invariants,
- selected/avoided mutual exclusion,
- required evidence metadata is present.

Do not derive both sides of an invariant from the same value.

Keep failed artifacts. Use a new artifact tag after a correction.

## Adoption Policy

A feature remains disabled unless all defined gates pass.

At minimum:

- all tests pass,
- targeted mechanics evidence passes,
- no crashes, stalls, deadlocks, or timeouts,
- the feature creates non-zero relevant opportunities,
- selected errors decrease,
- selection changes are attributable to the feature,
- ON vs Basic does not regress more than 2 percentage points,
- ON vs OFF is at least 50%,
- ON vs SafeRandom is at least 95%,
- spread and focus-fire behavior do not collapse.

Correct implementation alone is not enough for adoption. Sparse evidence is
not enough. Do not weaken a failed gate by calling it sample noise.

Correctness bug fixes to already adopted behavior may be retained without
enabling a new broad feature, but must still have regression tests.

## Audit Semantics

Candidate-level observations must not inflate selected-action error metrics.

For per-slot safety features, prefer:

```text
candidate_blocked
selected
avoided
only_legal
```

For ordinary non-only-legal decisions:

```text
candidate_blocked == selected + avoided
```

`selected` and `avoided` must be mutually exclusive.

Store structured selected-action metadata:

- action kind,
- move ID,
- target position,
- switch species,
- only-legal status.

Do not parse display strings when structured order data is available.

## Documentation

Update `walkthrough.md` after verified work.

Document:

- root cause,
- changed files,
- exact behavior,
- tests and exit codes,
- watchdog settings,
- targeted evidence,
- benchmark rows,
- artifact validation,
- adoption gate table,
- exact final defaults,
- confirmation that Phase 7 was not started.

If an earlier report was invalid, mark it rejected or superseded. Do not leave
contradictory “PASS” claims without clarification.

## Communication

- Write code, comments, prompts, reports, and documentation in English unless
  the user explicitly asks otherwise.
- Be concise but include exact counts, exit codes, artifact paths, and failed
  gates.
- Do not report a task complete while a required process is still running.
- Do not ask whether to wait for a benchmark; monitor it with watchdogs and
  finish the requested workflow.
- Stop and request review before changing adopted defaults unless the user has
  already authorized adoption under explicit gates.

## Current Priority

The immediate correctness priority is Phase 6.3.8 support-move target hard
safety, including the observed case where Blissey used Heal Pulse on an
opponent.

The feature must prove that wrong-side support candidates are present and
avoided before any default adoption. Preserve legitimate dual-purpose behavior
such as Pollen Puff damaging an opponent and healing an ally.
