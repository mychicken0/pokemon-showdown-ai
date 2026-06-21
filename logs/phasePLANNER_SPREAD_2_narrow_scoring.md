# PLANNER-SPREAD-2 — Narrow Spread Defense Scoring Implementation Report

## Status
**`IMPLEMENTED_OPT_IN_DEFAULT_OFF`** — Narrow scoring added. Default OFF. 187/187 tests pass (19 new). No behavior change when flag is OFF.

## Goal
Implement narrow spread defense scoring. Reuse existing per-move policy pattern. Default OFF. No default flip. No scoring change unless flag ON.

## Implementation summary

### 1. Config flags (default OFF)

```python
class DoublesDamageAwareConfig:
    # PLANNER-SPREAD-2: opt-in narrow spread defense scoring.
    enable_planner_spread_defense_scoring: bool = False
    planner_spread_defense_wg_bonus: float = 150.0
    planner_spread_defense_min_confidence: float = 0.5
    planner_spread_defense_max_picks_per_game: int = 3
    planner_spread_defense_min_turn_between_picks: int = 2
```

### 2. Eligible check (`_planner_spread_defense_eligible`)

6 guards (all must pass):
0. `enable_planner_spread_defense_scoring` is True (master switch)
1. `enable_planner_intent_detector` is True (detector must be running)
2. IntentDecision exists and `intent == "SPREAD_DEFENSE"`
3. Move is Wide Guard (normalized: "wideguard")
4. Confidence >= `planner_spread_defense_min_confidence` (0.5)
5. Opp pressure detected (reuses `_slot_in_opp_pressure`)
6. Anti-spam: pick count + min turn between picks

### 3. Bonus application

In `_score_action_impl`, after the existing anti-setup-disruption bonus block:

```python
if self._planner_spread_defense_eligible(order, active_idx, battle):
    score = float(score) + float(
        self.config.planner_spread_defense_wg_bonus
    )
    self._planner_spread_defense_record_pick(battle, active_idx)
```

Bonus magnitude: +150.0 (smaller than existing `wide_guard_spread_pressure_bonus=500.0`).

### 4. Anti-spam tracking

```python
self._planner_spread_defense_picks_per_game: Dict[str, int]  # battle_tag -> count
self._planner_spread_defense_last_pick_turn: Dict[str, int]  # battle_tag -> turn
```

Default max 3 picks per game, min 2 turns between picks.

### 5. Audit fields (observational)

Two new fields in `state_snapshot`:
- `planner_spread_defense_bonus_applied`: float (default 0.0)
- `planner_spread_defense_picks_this_game`: int (default 0)

These are observational; they do not affect scoring when the flag is OFF.

## Test coverage (19 new tests, file: `test_planner_spread_scoring.py`)

| class | tests | covers |
|---|---|---|
| TestEligibleDefaults | 2 | flag OFF → never eligible |
| TestMoveGuard | 3 | Wide Guard required |
| TestIntentGuard | 3 | intent must be SPREAD_DEFENSE |
| TestConfidenceGuard | 2 | confidence threshold |
| TestOppPressureGuard | 2 | opp pressure required |
| TestAntiSpam | 3 | per-game count + min turn gap |
| TestPickRecording | 1 | counter increments correctly |
| TestConfigDefaults | 3 | default OFF, small bonus |

### All test suites

| suite | tests | status |
|---|---|---|
| test_planner_spread_moves_fix | 36 | ✓ |
| test_planner_spread_scoring | 19 | ✓ (new) |
| test_bot_vgc2026_scripted_opp | 17 | ✓ |
| test_scenario_probe | 67 | ✓ |
| test_doubles_intent_classifier | 33 | ✓ |
| test_planner_intent_detector | 15 | ✓ |
| **Total** | **187** | **✓** |

## Stable state (per AGENTS.md)

- 187 unit tests pass
- 0 scoring change (default OFF)
- 0 default flips
- 0 `test_51` touched
- 0 audit logger behavior change (additive only)
- 0 model artifacts
- 0 V3d.1 / RL / Phase 7
- 0 new battles

## Adoption gates (per PLANNER-IMPL-1)

| gate | status | next |
|---|---|---|
| 1. Static/unit tests | ✓ 187/187 pass | done |
| 2. Fixture tests | ✓ 19 new | done |
| 3. Targeted probe (1 battle, flag ON) | pending | PLANNER-SPREAD-3 |
| 4. Smoke (5-20 pairs, OFF vs ON) | pending | PLANNER-SPREAD-3 |
| 5. Full benchmark (100 pairs) | pending | PLANNER-SPREAD-4 |
| 6. Adoption (user explicit approval) | pending | post-Gate 5 |

## Files

| action | file | lines |
|---|---|---:|
| MOD | `bot_doubles_damage_aware.py` | +150 (config + eligible + record_pick + bonus) |
| MOD | `doubles_decision_audit_logger.py` | +15 (2 audit fields) |
| NEW | `test_planner_spread_scoring.py` | +279 (19 fixture tests) |

## What's NOT done (per user's plan)

- [ ] Targeted probe (1 battle, flag ON) — PLANNER-SPREAD-3
- [ ] Smoke (5-20 pairs, OFF vs ON) — PLANNER-SPREAD-3
- [ ] Full benchmark (100 pairs) — PLANNER-SPREAD-4
- [ ] Default flip — requires user explicit approval

## Recommended next step

**PLANNER-SPREAD-3**: Targeted probe + smoke
- 1 battle with flag ON to verify WG boost fires correctly
- 5-20 pair smoke comparing OFF vs ON
- Verify WG selection count is > 0 when SPREAD_DEFENSE intent fires
- Verify bonus magnitude is correct (+150.0)
- Verify anti-spam works (max 3 picks per game)

## Decision label

**`IMPLEMENTED_OPT_IN_DEFAULT_OFF`** — narrow scoring implemented behind default OFF flag. 19 fixture tests pass. No scoring change. Adoption gates 1-2 cleared; gates 3-5 pending.
