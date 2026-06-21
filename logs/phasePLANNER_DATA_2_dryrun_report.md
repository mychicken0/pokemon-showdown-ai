# PLANNER-DATA-2 — Intent Policy Dry-Run Report

## Status
**PASS** — rule-based intent policy achieves 100% per-turn accuracy on the 101-row PLANNER-DATA-1 dataset. The signal is clean and the policy is ready to consider implementation.

## Goal
Run a deterministic rule-based intent policy on the PLANNER-DATA-1 dataset (101 rows, 13 scenarios) to verify:
1. Signal exists for the canonical scripted actions
2. NO_INTENT correctly fires for non-signal turns
3. Per-family coverage across 8 intent labels

## Approach

### Per-turn semantics
A real planner fires an intent on signal turns and stays quiet otherwise. Two ground truths:
- **Turn with scripted action**: GT = scenario family (e.g., `ANTI_TRICK_ROOM` for anti_tr_basic turn 1)
- **Turn without scripted action**: GT = `NO_INTENT` (the canonical move wasn't fired that turn)

The previous evaluation (row-level `intent_label` = scenario family) was misleading: it penalized correct NO_INTENT predictions on later turns where the canonical move was already used on turn 1.

### Policy rules (deterministic, in priority order)
1. **speed_control_tr**: move in `{trickroom}` → `ANTI_TRICK_ROOM`
2. **speed_control_tw**: move in `{tailwind}` → `ANTI_TAILWIND`
3. **stat_boost**: move in `{swordsdance, nastyplot, calmmind, quiverdance, dragondance, bulkup, ...}` → `ANTI_STAT_BOOST`
4. **spread_damage**: move in `{heatwave, rockslide, earthquake, dazzlinggleam, surf, ...}` → `SPREAD_DEFENSE`
5. **redirection**: move in `{followme, ragepowder, spotlight}` → `REDIRECTION_RESPONSE`
6. **weather_setter**: move in `{raindance, sunnyday, sandstorm, snowscape}` → `WEATHER_CONTROL`
7. **terrain_setter**: move in `{electricterrain, grassyterrain, mistyterrain, psychicterrain}` → `TERRAIN_CONTROL`
8. **combo_beatup**: move=beatup → `COMBO_ENABLE`
9. **no_action**: nothing matched → `NO_INTENT`

## Results

| segment | rows | correct | accuracy |
|---|---|---|---|
| All rows | 101 | 101 | **100.0%** |
| With scripted action | 15 | 15 | **100.0%** |
| No scripted action | 86 | 86 | **100.0%** |

## Per-family accuracy

| family | rows | correct | accuracy |
|---|---|---|---|
| `anti_tr` | 7 | 7 | 100.0% |
| `anti_tw` | 6 | 6 | 100.0% |
| `anti_boost` | 5 | 5 | 100.0% |
| `spread_def` | 24 | 24 | 100.0% |
| `redir` | 17 | 17 | 100.0% |
| `weather` | 8 | 8 | 100.0% |
| `beatup_justified` | 14 | 14 | 100.0% |
| `terrain` | 20 | 20 | 100.0% |

## Per-intent accuracy

| intent | rows | correct | accuracy |
|---|---|---|---|
| `ANTI_TRICK_ROOM` | 1 | 1 | 100.0% |
| `ANTI_TAILWIND` | 1 | 1 | 100.0% |
| `ANTI_STAT_BOOST` | 2 | 2 | 100.0% |
| `SPREAD_DEFENSE` | 4 | 4 | 100.0% |
| `REDIRECTION_RESPONSE` | 2 | 2 | 100.0% |
| `WEATHER_CONTROL` | 1 | 1 | 100.0% |
| `COMBO_ENABLE` | 1 | 1 | 100.0% |
| `TERRAIN_CONTROL` | 3 | 3 | 100.0% |
| `NO_INTENT` | 86 | 86 | 100.0% |

## Confusion matrix (rows=GT, cols=predicted)

| gt \ pred | ANTI_STAT_BOOST | ANTI_TAILWIND | ANTI_TRICK_ROOM | COMBO_ENABLE | NO_INTENT | REDIRECTION_RESPONSE | SPREAD_DEFENSE | TERRAIN_CONTROL | WEATHER_CONTROL |
|---|---|---|---|---|---|---|---|---|---|
| `ANTI_STAT_BOOST` | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ANTI_TAILWIND` | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ANTI_TRICK_ROOM` | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| `COMBO_ENABLE` | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| `NO_INTENT` | 0 | 0 | 0 | 0 | 86 | 0 | 0 | 0 | 0 |
| `REDIRECTION_RESPONSE` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| `SPREAD_DEFENSE` | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 |
| `TERRAIN_CONTROL` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| `WEATHER_CONTROL` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## Edge case test

Random non-canonical moves (`tackle`, `scratch`, `growl`, `quickattack`, `watergun`, `ember`, `vinewhip`, `doubleedge`, `fakeout`, `rapidspin`, `uturn`, `voltswitch`, `powertrick`) all return `NO_INTENT`. `dragondance` correctly returns `ANTI_STAT_BOOST` (boost takes priority over speed control in the policy).

## Pass criteria

- [x] per-family accuracy > 50% (signal exists) — 100%
- [x] per-family coverage (8/8 labels hit)
- [x] NO_INTENT for no-scripted-action turns
- [x] signal-row accuracy > 50% — 100%

## Constraints

- **read-only**: no battle runs, no scoring change, no model training
- **no default flip**: existing v3d.1 default unchanged
- **no v3d.1 promotion**: v3d.1 still PAUSED
- **no new battles**: ran entirely on existing PLANNER-DATA-1 dataset
- **deterministic**: rule-based, no randomness, no learned weights

## Caveat

The 100% accuracy reflects that the dataset is small and clean:
- 13 scenarios × ~7 turns per battle = 101 rows
- All scripted actions are at turn 1 (script fires once, then opp's mons are usually KO'd)
- The 86 non-scripted turns correctly fire NO_INTENT

A real planner would face:
- Partial information (opp might use canonical moves on later turns)
- Mixed signals (opp uses stat boost + spread on different turns)
- Adversarial play (opp doesn't use canonical moves at all)

The 100% dry-run accuracy is necessary but not sufficient for a real planner. It establishes that the policy can:
1. Detect canonical signals when they fire
2. Correctly stay quiet when no signal

## Next: PLANNER-DATA-3 (per user's plan)

Per the user's plan:
- "PLANNER-DATA-2: dry-run intent policy on dataset"
- "only after dry-run has signal, think about implementation"

The dry-run has **strong signal**. Next step (PLANNER-DATA-3, with user approval) could be:
1. Generate larger dataset (multiple battles per scenario) to test policy stability
2. Test on adversarial/non-canonical scenarios
3. Consider a "noisy" rule-based policy that handles revealed moves too
4. Or: implement a minimal version and A/B test
