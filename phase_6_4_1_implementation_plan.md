# Phase 6.4.1 - Known-Type Switch Candidate Ranking

You are implementing the next conservative Phase 6 improvement for the local-only
Pokemon Showdown doubles bot.

## Project

- Server: `/home/phurin/Program/Showdown_AI/pokemon-showdown`
- Bot: `/home/phurin/Program/Showdown_AI/pokemon-showdown-ai`
- Format: `gen9randomdoublesbattle`
- Main player: `bot_doubles_damage_aware.py`

Keep all work local-only. Do not connect to the official server, scrape websites,
use browser automation, call online APIs or LLMs during battle decisions, infer
hidden moves/items/abilities, enable full ability awareness, or start Phase 7.

## Verified Root Cause

`score_action()` currently returns `0.0` before processing a switch when
`battle.active_pokemon[active_idx]` is empty. During a forced replacement after a
faint, this can give every legal switch candidate the same score. The selected
replacement may therefore depend on legal-order ordering rather than matchup.

Switch candidates also currently share the same `switch_baseline` and are not
ranked by their known type matchup into the two visible opposing active Pokemon.

## Goal

Rank legal switch candidates using only currently visible Pokemon types and HP.
This must fix obvious cases such as selecting a Grass-type replacement into two
visible Fire-type opponents when a materially safer legal replacement exists.

This phase chooses the safest candidate after a switch is already legal or
preferred. It must not broadly increase voluntary switch frequency.

Do not implement stat-drop-driven switching yet. Add diagnostics for it so Phase
6.4.2 can be based on evidence.

## Required Config

Add conservative, disabled-by-default fields to `DoublesDamageAwareConfig`:

```python
enable_switch_candidate_type_safety: bool = False
switch_candidate_super_effective_penalty: float = 80.0
switch_candidate_quad_weak_penalty: float = 160.0
switch_candidate_double_threat_penalty: float = 100.0
switch_candidate_resistance_bonus: float = 20.0
switch_candidate_immunity_bonus: float = 30.0
switch_candidate_low_hp_penalty: float = 30.0
```

Do not change any Phase 6.3 defaults during implementation or before benchmark
acceptance.

## Known-Type Safety Helper

Create a helper with a structured return value:

```python
def evaluate_switch_candidate_type_safety(candidate, opponent_actives) -> dict:
    ...
```

Use only:

- `candidate.type_1` and `candidate.type_2`
- each currently visible opponent's `type_1` and `type_2`
- `candidate.damage_multiplier(opponent_type)` when safely available
- candidate current HP fraction

Never use species-based move assumptions, random-set data, possible abilities,
hidden moves, hidden items, or unrevealed information.

For each opponent, calculate the maximum incoming multiplier among that
opponent's visible types. Treat this as a conservative STAB-type exposure signal,
not predicted damage.

Return at least:

- raw safety score
- worst multiplier
- per-opponent worst multipliers
- super-effective threat count
- quad-weak threat count
- resistant threat count
- immune threat count
- double-threat boolean
- opponent threat type names
- candidate HP fraction

Unknown/missing types or multiplier errors must be neutral, not dangerous.

## Relative Ranking Rule

For each slot, evaluate all legal `Pokemon` switch orders.

The best legal switch candidate receives `0.0` score adjustment. Other switch
candidates receive only a non-positive relative adjustment based on the gap from
the best raw safety score:

```python
relative_adjustment = min(0.0, candidate_raw_score - best_raw_score)
```

This is mandatory. Do not give the best candidate a positive bonus. The feature
must rank switch candidates without making switching itself more attractive than
attacking, Protect, or other existing actions.

If every candidate is unsafe, keep all legal and select the least unsafe one.
Never hard-block a legal switch.

## Forced-Switch Fix

Refactor `score_action()` so switch orders are processed even when the active
slot is empty or fainted.

Requirements:

1. Pass/default handling remains legal.
2. A `Pokemon` switch order is scored before any early return requiring an
   active Pokemon.
3. Speed/priority switch logic may run only when a live active Pokemon exists.
4. Move scoring must still return `0.0` when no active attacker exists.
5. Both single-slot and simultaneous double forced-switch requests must work.

Do not special-case species such as Grass or Fire. The result must come from the
generic type matchup calculation.

## Stat-Drop Diagnostics Only

Add a helper that summarizes current revealed boost stages:

```python
def summarize_negative_boosts(pokemon) -> dict:
    ...
```

Record negative stages from the Pokemon's current `boosts` only. Do not alter
scores based on this helper in Phase 6.4.1.

At minimum report:

- total negative stages
- lowest stage
- offensive negative stages (`atk`, `spa`)
- defensive negative stages (`def`, `spd`)
- speed negative stage
- severe negative boost boolean
- whether the selected action was a switch

This data is for the Phase 6.4.2 decision only.

## Audit Logging

Modify `doubles_decision_audit_logger.py` with selected-action fields:

- `forced_switch`
- `switch_candidate_type_safety_applied`
- `selected_switch_species`
- `selected_switch_types`
- `selected_switch_hp_fraction`
- `selected_switch_raw_safety_score`
- `selected_switch_relative_adjustment`
- `selected_switch_worst_multiplier`
- `selected_switch_double_threat`
- `unsafe_switch_candidate_selected`
- `safer_switch_candidate_available`
- `best_safe_switch_species`
- `best_safe_switch_score`
- `switch_type_safety_avoided`
- negative-boost diagnostic fields listed above

Definitions:

- `unsafe_switch_candidate_selected`: selected candidate has a visible
  super-effective exposure from both opposing active Pokemon, or a visible 4x
  exposure, and a materially safer legal candidate existed.
- `switch_type_safety_avoided`: the enabled ranking changed selection away from
  such an unsafe candidate.
- `safer_switch_candidate_available`: based only on legal candidates for that
  slot and the generic safety score.

Candidate evaluation must not inflate selected-action battle metrics. Separate
our bot cases from opponent cases when detectable.

## Analyzer And Inspector

Update `analyze_doubles_decision_audit.py` with a section:

`Switch Candidate Safety Report`

Print:

- forced-switch count
- unsafe switch candidates selected
- safer candidate available count
- switch type-safety avoided count
- selected double-threat count
- severe negative-boost switch count
- severe negative-boost non-switch count
- wins/losses
- sample battle tags, turns, selected candidate, types, multipliers, opposing
  threat types, and best safer alternative

Create:

`inspect_switch_candidate_safety_cases.py`

Filters:

- `--unsafe-selected`
- `--safer-available`
- `--avoided`
- `--forced`
- `--severe-negative-boost`
- `--battle <battle_tag>`
- `--filepath <jsonl>`

Print the selected joint order and top five alternatives when available.

## Tests

Create `test_doubles_switch_candidate_safety.py`.

Required tests:

1. A forced switch is scored when `active_pokemon[slot] is None`.
2. Grass candidate ranks below Water candidate into two Fire opponents.
3. Candidate weak to both visible opponents receives double-threat penalty.
4. A 4x weakness receives the configured quad weakness penalty.
5. Resistance and immunity are recognized from type multipliers.
6. Unknown opponent type data is neutral.
7. No species, move-set, item, possible-ability, or random-set inference occurs.
8. Best candidate receives exactly zero relative adjustment.
9. Worse candidates receive non-positive adjustments only.
10. Candidate ranking does not increase the best switch's baseline score.
11. With the feature disabled, legacy switch scores remain unchanged.
12. Voluntary switch frequency incentives remain unchanged because the best
    switch receives no positive adjustment.
13. When all candidates are unsafe, the least unsafe remains selectable.
14. Simultaneous double forced switches can be scored without crashes.
15. Speed/priority switch logic does not dereference a missing active Pokemon.
16. Stat-drop summary is diagnostic-only and does not change action scores.
17. Selected-action audit metrics do not count rejected candidates.

Also run:

```bash
venv/bin/python -m unittest \
  test_doubles_switch_candidate_safety.py \
  test_doubles_ability_hard_safety.py \
  test_doubles_mechanics_scoring.py \
  test_doubles_speed_priority.py \
  test_doubles_speed_priority_analysis.py
```

## Benchmark

Create `bot_doubles_switch_candidate_safety_benchmark.py`.

Run:

- Off vs `DoublesBasicAwarePlayer`: 500 battles
- On vs `DoublesBasicAwarePlayer`: 500 battles
- On vs Off: 500 battles
- On vs `DoublesSafeRandomPlayer`: 100 battles

Save:

- `logs/doubles_switch_candidate_safety_benchmark.csv`
- separate JSONL audit logs for every matchup

Print:

- wins, losses, win rate, average turns
- crashes, exceptions, timeouts, unfinished battles
- forced-switch count
- unsafe switch candidates selected
- safer switch candidate available
- switch type-safety avoided
- selected double-threat count
- spread usage
- focus-fire usage
- Protect usage
- severe negative-boost switch/non-switch diagnostic counts

## Adoption Gates

Enable `enable_switch_candidate_type_safety=True` by default only if:

- all tests pass
- all battles finish without crashes, exceptions, deadlocks, or timeouts
- unsafe forced switch selections materially decrease
- Grass-into-two-Fire-style double-threat selections approach zero when a safer
  legal candidate exists
- On vs Basic regression is no worse than `-2.00` percentage points
- On vs Off is at least `50%`
- On vs SafeRandom is at least `95%`
- spread and focus-fire usage do not collapse
- voluntary switch rate does not materially increase

If any gate fails, preserve implementation/tests/logs but keep the flag false and
document the exact failed gate.

## Documentation

Append Phase 6.4.1 to `walkthrough.md`:

- verified early-return root cause
- known-information restrictions
- relative-ranking design
- tests and exit code
- exact benchmark rows and safety metrics
- adoption table and decision
- exact final defaults
- note that stat-drop switching remains diagnostic-only for Phase 6.4.2
- confirm full ability awareness remains disabled
- confirm Phase 7 was not started

## Final Report

Report:

1. changed files
2. root-cause fix
3. test counts and exit code
4. all four benchmark rows
5. switch safety metrics
6. negative-boost diagnostic counts
7. adoption decision and exact defaults
8. confirmation that no hidden information, full ability awareness, official
   server connection, or Phase 7 work was used

