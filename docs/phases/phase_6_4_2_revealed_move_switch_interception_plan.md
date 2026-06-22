# Phase 6.4.2 - Revealed-Move One-Ply Defensive Switching

Implement a conservative one-ply defensive switch predictor for the local-only
Pokemon Showdown doubles bot.

## Restrictions

- Local server only.
- Never connect to official Pokemon Showdown.
- No scraping, browser automation, online APIs, or LLM calls during battles.
- Never infer hidden moves, items, or abilities from species.
- Never use random-set or meta data for this feature.
- Keep full ability awareness disabled.
- Do not implement stat-drop-driven switching in this phase.
- Do not start Phase 7.

## Objective

When an opponent has already revealed a damaging move that is dangerous to one
of our active Pokemon, evaluate one defensive ply:

1. opponent may select that revealed move;
2. opponent may rationally target the active Pokemon most vulnerable to it;
3. determine whether a legal switch candidate would take materially less
   damage;
4. reward the defensive switch only when preserving the active Pokemon is more
   valuable than its available immediate action.

Example:

- our active Pokemon is Grass-type;
- an opponent has already revealed a Fire-type damaging move;
- a legal bench Pokemon resists or is immune to Fire;
- the active is likely to take severe or lethal damage;
- the active does not have a high-value KO or equivalent action;
- the bot may switch the resistant candidate in to receive the predicted move.

Do not predict Fire coverage merely because the opponent's species often carries
Fire moves. The Fire move must be present in `opponent.moves`.

## Part 0 - Required Mechanics Closure

Complete these corrections before implementing prediction.

### Default consistency

The Phase 6.4.1a report and `walkthrough.md` adopted:

```python
enable_switch_candidate_type_safety = False
```

but the current source still sets it to `True`. Set the source default to
`False`, add an exact default assertion, and update any stale comments.

The corrected SafeRandom result was 94%, below the 95% adoption gate. Do not
reinterpret the decision.

### Zero-effectiveness tie safety

The Phase 6.4.1a On-vs-Basic log contains 27 selected type-immune damaging
actions despite `enable_type_immunity_safety=True`. These actions had score zero
but tied other zero-score legal actions, so legal-order ordering selected the
wasted move.

Examples include:

- Fighting into Ghost
- Normal into Ghost
- Ghost into Normal
- Dragon into Fairy
- Psychic into Dark
- Ground into Flying

Add a final joint-order hard-safety tie rule:

- a type-immune damaging single-target action is a guaranteed-waste action;
- if a complete legal joint order exists without that guaranteed-waste action,
  prefer the non-waste order even when numeric scores tie;
- do not suppress a partial spread move that still damages another opponent;
- preserve Thousand Arrows, Gravity, Scrappy, and Mind's Eye exceptions;
- if every legal order contains the immune action, classify it as only-legal;
- do not count opponent baseline mistakes as our bot mistakes.

Use deterministic tuple ordering or an explicit joint penalty that cannot be
erased by `max(score, 0.0)`.

Add explicit dual-type mechanics tests:

- Electric move into Electric/Ground target => `0.0`
- Electric move into Water/Flying target => `4.0`
- Fire move into Grass/Steel target => `4.0`
- Water move into Fire/Ground target => `4.0`
- Ground move into Electric/Flying target => `0.0` unless an existing exception
  applies
- a non-immune legal alternative wins a zero-score tie

Add audit separation:

- `our_type_immune_move_selected`
- `our_type_immune_only_legal`
- `our_type_immune_move_avoided`
- `opponent_type_immune_move_selected`
- attacker, move, target, target types, and reason

The opponent metric is observational only. Never alter the baseline opponent.

## Part 1 - Configuration

Add disabled-by-default fields:

```python
enable_revealed_move_switch_interception: bool = False
revealed_switch_min_threat_multiplier: float = 2.0
revealed_switch_min_risk_reduction: float = 0.50
revealed_switch_min_candidate_hp: float = 0.35
revealed_switch_likely_target_weight: float = 1.00
revealed_switch_tied_target_weight: float = 0.50
revealed_switch_ko_threat_bonus: float = 260.0
revealed_switch_severe_threat_bonus: float = 140.0
revealed_switch_resist_bonus: float = 45.0
revealed_switch_immunity_bonus: float = 70.0
revealed_switch_max_bonus: float = 320.0
revealed_switch_high_value_action_threshold: float = 250.0
revealed_switch_ko_action_override: bool = True
```

These values are initial experiment values, not adopted defaults.

Keep:

```python
enable_switch_candidate_type_safety = False
enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
```

## Part 2 - Revealed Damaging Move Helper

Create:

```python
def get_revealed_damaging_moves(opponent) -> list:
    ...
```

Rules:

- use only `opponent.moves.values()`;
- include only moves with reliable `base_power > 0`;
- retain move type, category, power, accuracy, priority, and target metadata;
- exclude status moves;
- never add STAB moves from visible opponent types;
- never query possible moves, species data, random sets, or meta models;
- unknown or malformed move data must be skipped safely.

## Part 3 - Dual-Type Incoming Risk

Create:

```python
def evaluate_revealed_move_incoming_risk(
    move,
    opponent,
    defender,
    battle=None,
) -> dict:
    ...
```

Use `defender.damage_multiplier(move)` so both defender types are combined by
the battle engine.

Return:

- type multiplier
- base power
- accuracy
- STAB based only on visible opponent types
- priority
- spread/single-target classification
- rough incoming pressure score
- immune/resisted/neutral/super-effective/quad classification
- likely KO pressure boolean

Do not use hidden items, hidden abilities, hidden EVs, or unrevealed moves.

Known type immunity must produce zero risk. In particular, Electric against an
Electric/Ground defender must produce zero.

Do not infer a target ability. Known ability hard safety may remain separate and
must not become full ability awareness.

## Part 4 - One-Ply Target Likelihood

Create:

```python
def estimate_revealed_move_target_likelihood(
    move,
    opponent,
    our_actives,
    battle=None,
) -> dict:
    ...
```

This is a transparent heuristic, not certainty.

For a single-target opposing move:

- evaluate its incoming risk against both our active Pokemon;
- if one active has materially higher multiplier/KO pressure, mark it the likely
  target with configured full weight;
- if risks are effectively tied, use configured tied-target weight for both;
- an immune active receives zero target threat from that move;
- do not predict targets using species, hidden moves, or hidden abilities.

For an opposing spread move:

- evaluate both active Pokemon independently;
- it threatens every legal affected target;
- do not use the single-target likelihood reduction.

Respect target metadata when reliable. Moves that cannot target an opponent must
not create switch-interception threat.

## Part 5 - Active Threat Summary

Create:

```python
def summarize_revealed_move_threats(
    active,
    active_idx,
    opponent_actives,
    our_actives,
    battle=None,
) -> dict:
    ...
```

Aggregate revealed moves without pretending the opponent uses all of them at
once. Use the highest credible weighted threat per opposing active, then combine
the two opponent contributions conservatively.

Return:

- threatening opponent species
- revealed move IDs and types
- target likelihood weights
- active multipliers
- priority/spread status
- maximum and combined pressure
- likely lethal threat
- super-effective threat
- no-threat reason

Do not count Electric as a threat to Electric/Ground.

## Part 6 - Switch Interception Value

Create:

```python
def evaluate_revealed_move_switch_interception(
    active,
    candidate,
    active_idx,
    battle,
) -> dict:
    ...
```

Compare each credible revealed threat against:

- the current active Pokemon;
- the candidate using its complete dual typing.

Return:

- active incoming risk
- candidate incoming risk
- absolute and fractional risk reduction
- moves resisted by candidate
- moves made immune by candidate
- moves that become more dangerous after switching
- candidate HP
- interception valid boolean
- rejection reason
- proposed score bonus before cap

A candidate is valid only if:

- the active has a credible revealed threat;
- candidate HP meets the configured minimum;
- candidate reduces weighted risk by the configured minimum;
- candidate is not exposed to an equal or worse revealed threat from the other
  opponent;
- the switch is legal;
- it does not conflict with the other slot's selected switch in the complete
  joint order.

Do not label a candidate safe merely because it resists one move if another
revealed opposing move severely threatens it.

## Part 7 - Action-Value Gate

The feature may increase voluntary switch score, so apply strict gates.

Before adding interception value:

1. calculate the active's best legal move/action score;
2. detect whether it has an expected KO;
3. detect a high-value spread or focus-fire contribution;
4. check whether it is expected to move before the revealed threat when speed
   information is reliable;
5. check whether Protect is legal and currently preferable.

Rules:

- expected KO blocks defensive switching when
  `revealed_switch_ko_action_override=True`, unless the active is likely to faint
  before moving;
- a best action above the configured high-value threshold strongly suppresses
  or rejects switching;
- low-value/status-only turns may receive the full interception bonus;
- likely lethal revealed threats receive the KO-threat bonus;
- nonlethal super-effective threats receive only the severe-threat bonus;
- cap all added score by `revealed_switch_max_bonus`;
- do not apply the bonus to forced switches;
- do not apply it when no damaging opponent move has been revealed.

This phase must not reward switching solely because an opposing Pokemon has a
type advantage. A specific revealed damaging move is required.

## Part 8 - Joint Doubles Integration

Evaluate complete legal joint orders.

- prevent both slots from selecting the same bench Pokemon;
- preserve the other slot's damage, KO, spread, focus-fire, and Protect value;
- compare interception orders against complete non-switch joint alternatives;
- do not call a switch successful if the partner action loss makes the total
  joint order worse;
- keep deterministic tie behavior;
- preserve Phase 6.3 hard safety and Phase 6.1 type immunity.

Record a counterfactual best joint order with the feature Off and compare it to
the selected On order.

## Part 9 - Audit Logging

Add selected-action and counterfactual fields:

- `revealed_switch_prediction_available`
- `revealed_switch_interception_selected`
- `revealed_switch_selection_changed`
- `revealed_switch_threatening_opponent`
- `revealed_switch_threat_move_ids`
- `revealed_switch_threat_move_types`
- `revealed_switch_target_likelihood`
- `revealed_switch_active_risk`
- `revealed_switch_candidate_risk`
- `revealed_switch_risk_reduction`
- `revealed_switch_candidate_species`
- `revealed_switch_candidate_types`
- `revealed_switch_candidate_hp`
- `revealed_switch_bonus_applied`
- `revealed_switch_blocked_by_ko_action`
- `revealed_switch_blocked_by_high_value_action`
- `revealed_switch_rejected_worse_other_threat`
- `revealed_switch_post_turn_damage_taken`
- `revealed_switch_post_turn_survived`
- `revealed_switch_predicted_move_used`
- `revealed_switch_prediction_correct`
- `revealed_switch_prediction_wrong`

Outcome correctness must be evaluated from local battle events only.

Do not claim prediction correctness merely because the switch survived. Confirm
whether the opponent actually used one of the predicted revealed moves and, when
detectable, whether its target/effect matched the interception.

Separate our decisions from opponent baseline mistakes.

## Part 10 - Analyzer and Inspector

Create:

`inspect_revealed_move_switch_cases.py`

Filters:

- `--selected`
- `--changed`
- `--correct`
- `--wrong`
- `--ko-blocked`
- `--high-value-blocked`
- `--worse-other-threat`
- `--electric-ground`
- `--our-type-immune-error`
- `--opponent-type-immune-error`
- `--battle`
- `--filepath`

Update `analyze_doubles_decision_audit.py` with:

`Revealed-Move Switch Interception Report`

Report action counts and unique battle counts separately:

- predictions available
- interceptions selected
- selections changed
- correct predictions
- wrong predictions
- survived interceptions
- candidate fainted
- KO/high-value overrides
- rejected worse-other-threat cases
- our type-immune errors
- opponent type-immune errors
- dual-type Electric/Ground cases
- wins/losses and sample turns

## Part 11 - Tests

Create:

`test_doubles_revealed_move_switch_interception.py`

Required tests:

1. No revealed damaging move => no prediction or bonus.
2. Revealed Fire move threatens Grass active.
3. Fire move is not inferred from a Fire species with no revealed Fire move.
4. Water candidate resists revealed Fire and receives interception value.
5. Grass/Steel active receives 4x Fire risk.
6. Electric/Ground active receives 0x Electric risk.
7. Water/Flying active receives 4x Electric risk.
8. Candidate dual typing is fully combined.
9. Single-target move prefers uniquely more vulnerable active.
10. Tied target likelihood uses configured partial weight.
11. Spread revealed move threatens both affected actives.
12. Candidate rejected when the other opponent has a revealed severe threat
    against it.
13. Candidate below minimum HP rejected.
14. Expected KO action blocks switch when active can move first.
15. Likely faint-before-moving may override the KO-action block.
16. High-value spread action suppresses switching.
17. Forced switches receive no interception bonus.
18. Same bench candidate cannot be assigned to both slots.
19. Prediction bonus is capped.
20. Feature Off leaves all scores unchanged.
21. Our immune move loses a zero-score tie to a non-immune legal action.
22. Partial spread immunity remains valid.
23. Thousand Arrows/Gravity/Scrappy exceptions remain valid.
24. Opponent type-immunity error is not counted as our bot error.
25. Correct and wrong prediction outcomes require local event evidence.
26. Default switch-candidate type safety is False.
27. Full ability/meta/random-set features remain False.

Run all existing suites plus the new suite.

## Part 12 - Benchmark

Create:

`bot_doubles_revealed_move_switch_interception_benchmark.py`

Run:

- Off vs Basic: 500
- On vs Basic: 500
- On vs Off: 500
- On vs SafeRandom: 100

Use new Phase 6.4.2 CSV and separate JSONL filenames.

Print:

- stability and win-rate fields
- average turns
- voluntary and forced switches
- predictions available
- interceptions selected
- selection changed
- correct/wrong prediction counts
- prediction precision
- survival after interception
- KO/high-value override counts
- our/opponent type-immune selections
- Electric/Ground immunity cases
- Protect, spread, and focus-fire usage
- severe negative-boost diagnostics unchanged from Phase 6.4.1a

## Part 13 - Adoption Gates

Enable `enable_revealed_move_switch_interception=True` only if:

- all tests pass;
- no crashes, exceptions, deadlocks, timeouts, or unfinished battles;
- our avoidable type-immune move selections approach zero;
- prediction-driven selections actually change in a nontrivial number of cases;
- prediction precision is at least 55%;
- intercepted Pokemon survival improves over comparable non-switch threats;
- On vs Basic regression is no worse than -2 percentage points;
- On vs Off is at least 50%;
- On vs SafeRandom is at least 95%;
- voluntary switch usage does not explode;
- Protect, spread, focus-fire, and KO conversion do not collapse.

If any gate fails, preserve code/tests/artifacts and keep the feature False.

## Part 14 - Documentation

Update `walkthrough.md` with:

- source/default inconsistency correction;
- the 27 zero-effectiveness tie cases and fix;
- explicit dual-type examples;
- difference between visible-type ranking and revealed-move prediction;
- exact tests and benchmark rows;
- prediction precision and outcome evidence;
- adoption decision and exact final defaults;
- stat-drop switching deferred to Phase 6.4.3;
- full ability awareness remains disabled;
- Phase 7 not started.

## Final Report

Return:

1. changed files;
2. mechanics-closure results, including Electric/Ground tests;
3. test count and exit code;
4. four benchmark rows;
5. prediction availability, selection, correctness, and survival metrics;
6. our vs opponent type-immunity errors;
7. adoption decision and exact defaults;
8. confirmation that hidden inference, full ability awareness, official server,
   Phase 6.4.3 scoring, and Phase 7 were not used.
