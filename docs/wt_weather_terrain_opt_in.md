# Weather/Terrain Positive Scoring — Opt-in Implementation

**Date**: 2026-06-23
**Phase**: WT-3 through WT-4g (closed as opt-in)
**Status**: `WT4G_OPT_IN_READY_DEFAULT_OFF`

```text
WT_STATUS: OPT_IN_IMPLEMENTED_DEFAULT_OFF
DEFAULT_ADOPTED: NO
READY_FOR_DEFAULT_ON: NO
READY_FOR_100_PAIR_BENCHMARK: NO
PHASE7_RELATED: NO
```

---

## 1. Summary

The Weather/Terrain (WT) investigation began as a
`SWITCH_SCORING_GAP` from Phase WT-2. Setters like
Rain Dance, Sunny Day, and the four terrains were
legal but never selected by the bot. A 7-phase
investigation (WT-3 → WT-4g) traced, fixed, and
validated the opt-in positive scoring path.

* **WT-2** (closed earlier): confirmed the gap via
  setter audit.
* **WT-3**: added opt-in positive scoring with a
  conservative 150/120 bonus.
* **WT-4a**: bonus sweep + Misty Terrain signal fix
  + bad-setter detector. Tuned defaults: 500/400.
* **WT-4b**: score-rank attribution + forced-synergy
  debugging. Identified that setters were pre-filtered
  out of the scoring path.
* **WT-4c**: candidate inclusion helper
  (`should_include_weather_terrain_setter_candidate`)
  integrated into bot candidate generation.
* **WT-4d**: forced synergy activation smoke. Found
  lead selection puts setter on bench.
* **WT-4e**: 2-Pokemon teams to guarantee setter is
  active. Still 0 selections — deep integration issue.
* **WT-4f**: **found and fixed the real root cause**:
  the WT hook was below a status-move early return
  inside `_score_action_impl`. Status setters returned
  before the hook fired. Moved the hook to the
  beginning of the function. First real setter
  selection observed: Jolteon `electricterrain` score
  400 in turn 1.
* **WT-4g**: regression guards + small OFF vs ON
  paired eval. All 19 regression tests pass. 5/5
  pairs both arms. Flag OFF = 0 positive bonus.
  Flag ON = 25 positive bonus in 5 pairs.

**Final result**: opt-in implemented, default OFF,
validated locally. WT is **not** default-adopted and
the default must not be flipped without a future
qualification phase.

---

## 2. Root Cause

```text
Weather/Terrain setters are status moves.
The original WT hook was below a status-move early
return inside _score_action_impl.
Therefore setters like Rain Dance, Sunny Day,
Electric Terrain, etc. returned before WT scoring
was applied.
```

The status-move block (around line 6850) returned
`0.0` or `10.0` for any move with `base_power == 0`
when the active Pokemon also had a damaging move,
or when the WT-3 inclusion helper rejected. The
WT-3 hook at line 8399 ran *after* the function's
status-move early return, so it never saw setter
orders at all.

WT-4e confirmed this empirically:
`get_weather_terrain_positive_bonus` was monkey-
patched to log every call. Across an entire
2-Pokemon terrain battle, the hook was called 0
times for `electricterrain` even though the scoring
loop iterated over it.

---

## 3. Fix

The WT-3 hook now runs at the **very beginning**
of `_score_action_impl`, before any other check
(line 6241 in `showdown_ai/bot_doubles_damage_aware.py`):

```python
_wt3_pending_bonus = 0.0
score = 0.0
try:
    from doubles_engine.wt3_weather_terrain_positive import (
        get_weather_terrain_positive_bonus as _wt3_get_bonus,
    )
    _wt3_pending_bonus, _wt3_pending_reason = _wt3_get_bonus(
        order, active_idx, battle, config=self.config
    )
    # record in self._wt3_decisions
    ...
except Exception:
    _wt3_pending_bonus = 0.0
```

The bonus is **deferred** to the final return:

```python
return max(score, 0.0) + _wt3_pending_bonus
```

This guarantees:

* the hook fires for **every** order, including
  status moves that previously returned early
* `_wt3_pending_bonus` is a **local variable** reset
  on every call — no leakage between candidates
* flag OFF → helper returns `(0.0, "")` → no score
  change
* non-WT status moves (e.g. `thunderwave`) → helper
  returns `(0.0, "")` → no change

---

## 4. Safety Guarantees

* **master flag** `enable_weather_terrain_positive_scoring`
  default `False` — preserved.
* **no behavior change when flag OFF** — helper
  returns `(0.0, "")`; bonus is 0; old scoring
  path is unaffected.
* **no default flip** during WT-3 through WT-4g.
* **no Anti-Trick-Room change** — WT path does not
  touch Anti-TR; PLANNER-ANTI-TR remains a separate
  opt-in feature.
* **no species-based ability inference** — the
  helper only inspects revealed active Pokemon
  types, revealed own moves, and revealed opponent
  moves. No Swift Swim / Chlorophyll / Sand Rush /
  Slush Rush is inferred from species.
* **no Magic Bounce species inference** — never
  added.
* **no official server** — all smoke runs use
  `localhost:8000`.
* **no Phase 7** — this is not RL training and is
  not a model artifact.
* **no model training** — pure scoring + opt-in
  helper, no ML pipeline.
* **hard safety** still runs before unsafe action
  execution. The WT-3 hook is *not* a bypass.
* **bad/redundant setter guards** — redundant
  setter prevention (no bonus if target weather/
  terrain already active) and opponent-benefit
  penalty (net score = own − opp; no bonus if
  net ≤ 0) are part of the helper.

---

## 5. Validation

### 5.1 Unit / regression tests

```text
517/517 tests PASS (498 from before + 19 new WT-4g tests)
```

New regression module:
`tests/test_wt4g_early_hook_regression.py` (19 tests):

| Category | Tests |
|----------|------:|
| `_wt3_pending_bonus` resets per candidate | 2 |
| `_wt3_pending_bonus` resets after early return | 2 |
| Flag OFF unchanged | 2 |
| Flag ON + synergy positive | 2 |
| Non-WT status move unaffected | 2 |
| Redundant WT setter rejected | 2 |
| Opponent benefits more rejected | 2 |
| No species-based ability inference | 2 |
| Zero bonus config rejected | 1 |
| Anti-TR unchanged | 1 |
| Independent calls (helper purity) | 1 |

### 5.2 Activation guard (WT-4f)

```text
6 battles  (3 modes × 2 battles)
44 setter decisions
5 positive bonuses
4 setters selected
0 bad/redundant setters
3/3 modes with setter active, positive bonus, and selection
```

### 5.3 Small paired eval (WT-4g)

5 pairs OFF vs ON, terrain mode (Jolteon + Garchomp
vs Tyranitar + Gyarados), 500/400 bonus:

| Arm | Finished | WT-3 calls | Setter calls | Positive bonus | Bad setters |
|-----|---------:|-----------:|-------------:|---------------:|------------:|
| OFF | 5/5 | 758 | 20 | **0** | 0 |
| ON  | 5/5 | 392 | 40 | **25** | 0 |

* No crashes, no errors.
* First WT setter selected: Jolteon
  `electricterrain` with score 400.0 in turn 1
  of `battle-gen9doublescustomgame-100890`.
* Flag OFF: hook records 0 bonus (correct).
* Flag ON: 25/40 setter calls got positive bonus
  (62% activation in favorable matchups).

---

## 6. Files Introduced

### Implementation

* `doubles_engine/wt3_weather_terrain_positive.py`
  — pure helper, no side effects. Includes
  `get_weather_terrain_positive_bonus`,
  `should_include_weather_terrain_setter_candidate`,
  `is_wt3_setter_move`, `is_bad_setter_selection`,
  bad-setter reason constants.
* `doubles_engine/wt4b_rank_attribution.py`
  — pure analysis helper for setter attribution.
* `showdown_ai/bot_doubles_damage_aware.py`
  — early WT hook at start of `_score_action_impl`
  (line 6241), pending bonus at final return
  (line 6717), `_wt3_decisions` recorder,
  `_wt4c_inclusions` observer.

### Tests

* `tests/test_wt3_weather_terrain_positive.py`
  (64 tests)
* `tests/test_wt4b_rank_attribution.py` (27 tests)
* `tests/test_wt4g_early_hook_regression.py`
  (19 tests)

### Local smoke / eval scripts

* `showdown_ai/bot_wt3_smoke_local.py`
* `showdown_ai/bot_wt4a_bonus_sweep_local.py`
* `showdown_ai/bot_wt4d_forced_synergy_smoke_local.py`
* `showdown_ai/bot_wt4e_active_setter_smoke_local.py`
* `showdown_ai/bot_wt4g_simple_paired_eval.py`
* `showdown_ai/bot_wt4g_small_paired_eval_local.py`

### Custom local fixtures

* `data/curated_teams/custom/wt4d_rain_favorable_opp.json`
* `data/curated_teams/custom/wt4d_sun_favorable_opp.json`
* `data/curated_teams/custom/wt4d_terrain_favorable_opp.json`
* `data/curated_teams/custom/wt4e_rain_2mon.json`
* `data/curated_teams/custom/wt4e_rain_2mon_opp.json`
* `data/curated_teams/custom/wt4e_rain_fast_setter_team.json`
* `data/curated_teams/custom/wt4e_sun_2mon.json`
* `data/curated_teams/custom/wt4e_sun_2mon_opp.json`
* `data/curated_teams/custom/wt4e_sun_fast_setter_team.json`
* `data/curated_teams/custom/wt4e_terrain_2mon.json`
* `data/curated_teams/custom/wt4e_terrain_2mon_opp.json`
* `data/curated_teams/custom/wt4e_terrain_fast_setter_team.json`

### Phase logs

* `logs/wt_3_weather_terrain_positive_scoring.md`
* `logs/wt_4a_bonus_sweep_activation_tuning.md`
* `logs/wt_4b_score_rank_attribution.md`
* `logs/wt_4c_candidate_inclusion_fix.md`
* `logs/wt_4d_forced_synergy_activation.md`
* `logs/wt_4e_active_setter_activation.md`
* `logs/wt_4f_deep_integration_fix.md`
* `logs/wt_4g_small_paired_eval.md`
* `logs/wt4g_small_paired_eval.json`
* `logs/wt4g_activation_guard.json`
* `logs/wt4f_root_cause.json`
* `logs/wt4f_all.json`
* `logs/wt4c_candidate_inclusion_attribution.json`
* `logs/wt4d_forced_synergy_activation.json`

---

## 7. What NOT to do next

* **Do not default-enable WT** (`enable_weather_terrain_positive_scoring=True`).
  The path is opt-in by design.
* **Do not run a 100-pair benchmark** just for WT
  before moving on. WT-4g's 5-pair smoke + 517
  passing tests are sufficient closure evidence.
* **Do not treat WT as RL training.** WT is a
  scoring feature, not a model.
* **Do not infer abilities from species.** No
  Chlorophyll / Swift Swim / Sand Rush / Slush Rush
  shortcuts.
* **Do not revive old Anti-TR / Magic Bounce species
  inference.** The WT path is silent on those
  features.

---

## 8. Future work (not committed)

* **Optional larger paired eval** can be run later
  if a broader gameplay impact is desired.
* **Possible default adoption** would require a
  new qualification phase with paired gates
  passing (≥ 50% ON vs OFF, no winrate collapse,
  no selection collapse). The 5-pair WT-4g smoke
  is **not** a sufficient qualification.
* **RL data refresh** could include WT opt-in
  datasets later if RL training is approved.
  Phase 7 is **not** approved.

---

## 9. Closure decision

```text
WT4G_OPT_IN_READY_DEFAULT_OFF
```

WT is technically implemented and validated as
opt-in. No further evaluation is required before
moving on to the next priority phase.
