# PLANNER-IMPL-2b — Observational Runtime Smoke Report

## Status
**PASS** — 9/9 pass criteria met. 10/10 battles ok. Flag ON adds audit fields only; no scoring change, no default behavior change.

## Goal
Runtime smoke test of the per-turn `IntentDetector`:
- 5 OFF + 5 ON battles
- Verify no crashes / stalls
- Verify audit fields present and correct
- Verify flag ON does NOT change scoring

## Result summary

| metric | OFF arm | ON arm | threshold |
|---|---|---|---|
| Battles ok | 5/5 | 5/5 | 10/10 |
| Win/Loss | 2W/3L | 3W/2L | (within noise) |
| Audit fields present | 29/29 | 37/37 | 100% |
| intent_label None | 100% | 0% | as expected |
| intent_label valid | n/a | 100% | ≥99% |
| intent_changed_selection=False | 29/29 | 37/37 | 100% |
| bonus_applied=0.0 | 29/29 | 37/37 | 100% |
| Timeout/error | 0 | 0 | 0 |

## Pass criteria (9/9)

| criterion | status |
|---|---|
| 10/10 battles ok | ✓ |
| audit JSONL exists | ✓ |
| planner_intent_* present in state_snapshot | ✓ |
| flag OFF rows have None/0/False | ✓ |
| flag ON rows emit valid intents | ✓ |
| bonus_applied == 0.0 always | ✓ |
| changed_selection == False always | ✓ |
| no timeout/error | ✓ |
| no default behavior change (no scoring bonus applied) | ✓ |

## Label distribution (ON arm)

| intent | count | % of total |
|---|---|---|
| NO_INTENT | 29 | 78.4% |
| SPREAD_DEFENSE | 8 | 21.6% |
| ANTI_TRICK_ROOM | 0 | 0% |
| ANTI_TAILWIND | 0 | 0% |
| ANTI_STAT_BOOST | 0 | 0% |

Interpretation: 8 SPREAD_DEFENSE fires correspond to the 5 pair configs, where team 006/020/027/046/057 all include spread attackers (Heat Wave, Rock Slide, Earthquake, etc.). The other 3 intents (ANTI_TR/TW/STAT_BOOST) didn't fire in this smoke because no real bot uses Trick Room / Tailwind / stat-boost setup in this pair set (the bots are offensive/control, not setup).

This is consistent with PLANNER-DATA-3 finding: real-data intent distribution is sparse (most battles are offensive, not setup).

## Sample audit record (ON arm, turn 1)

```json
{
  "turn": 1,
  "state_snapshot": {
    "our_active_species": ["garchomp", "tyranitar"],
    "opp_active_species": ["volcarona", "snorlax"],
    "weather": [],
    "fields": [],
    "side_conditions": [],
    "planner_intent_label": "SPREAD_DEFENSE",
    "planner_intent_confidence": 0.65,
    "planner_intent_matched_moves": ["dazzlinggleam"],
    "planner_intent_evidence_source": "revealed_moves",
    "planner_intent_routed_to_policy": "spread_defense",
    "planner_intent_bonus_applied": 0.0,
    "planner_intent_changed_selection": false
  },
  "selected_joint_order": "/choose move dazzlinggleam, switch Basculegion"
}
```

## Behavior parity check

**Note**: OFF and ON arms run SEPARATE battles (different random outcomes). Direct `selected_joint_order` comparison is not meaningful.

Parity is verified via audit fields:
- `planner_intent_bonus_applied == 0.0` in BOTH arms (no scoring bonus)
- `planner_intent_changed_selection == False` in BOTH arms (no selection change)

The detector only LOGS intent; it does not affect scoring or selection.

## Stable state (per AGENTS.md)

- 132 unit tests pass (84 + 33 + 15)
- 0 scoring change
- 0 default flips
- 0 audit logger behavior change
- 0 model artifacts
- 0 V3d.1 / RL / Phase 7
- 5+5 = 10 new battles (real showdown server)

## Files

| action | file | lines |
|---|---|---:|
| NEW | `bot_doubles_planner_intent_smoke.py` | +500 (smoke runner) |
| NEW | `logs/vgc2026_phasePLANNER_IMPL_2b_*_treatment_audit.jsonl` | 10 records |
| NEW | `logs/phasePLANNER_IMPL_2b_validation.json` | summary stats |

## Recommendation

PLANNER-IMPL-2 is observably stable. Next steps (with user approval):
- **PLANNER-IMPL-2c (optional 20-pair)**: confirm stability at slightly larger sample (no regression in crashes / stalls)
- **PLANNER-IMPL-3 (deferred intents)**: address REDIRECTION_RESPONSE target-aware scoring
- **PLANNER-IMPL-4 (audit tool integration)**: make the detector a permanent audit tool for new scenarios
- **NOT recommended**: full 100/200-pair benchmark (gate 5, requires Gate 1-4 to pass first)

The detector is ready to be a permanent audit tool. No further implementation needed unless user wants the deferred intents.

## Decision label
**`IMPLEMENTED_OBSERVATIONAL_OPT_IN`** (per PLANNER-IMPL-2) + **runtime smoke verified**
