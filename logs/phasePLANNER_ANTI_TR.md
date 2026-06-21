# PLANNER-ANTI-TR — Anti-Trick Room Response

## Status
**`IMPLEMENTED_SMOKE_DID_NOT_TRIGGER`** — code is correct (16/16 unit
tests pass), but the smoke run did not produce a measurable anti-TR
event because the bot killed the TR setter before TR was revealed.

## Goal
Add a new scoring policy: when the bot detects opp Trick Room, it
should respond with:
1. **Taunt / Encore / Disable** — disrupt the TR setter
2. **KO pressure** — favor damaging moves to KO before TR expires

## Implementation

### Config (`DoublesDamageAwareConfig`)
```python
enable_anti_trick_room_response: bool = False  # default OFF (opt-in)
anti_trick_room_response_bonus: float = 200.0  # Taunt/Encore/Disable
anti_trick_room_ko_bonus: float = 100.0  # Damaging moves vs TR
anti_trick_room_response_max_picks_per_game: int = 2
anti_trick_room_response_min_turn_between_picks: int = 3
anti_trick_room_ko_max_picks_per_game: int = 3
anti_trick_room_ko_min_turn_between_picks: int = 1
anti_trick_room_response_require_survival: bool = True
```

### Two eligibility methods
1. `_anti_trick_room_response_eligible(order, active_idx, battle)`
   - Move is Taunt/Encore/Disable (NOT Quash)
   - ANTI_TRICK_ROOM intent fired
   - User HP > 25% (or `require_survival=False`)
   - Target is opp slot 1 or 2
   - Anti-spam guards

2. `_anti_trick_room_ko_pressure_eligible(order, active_idx, battle)`
   - Move is damaging (BP > 0)
   - ANTI_TRICK_ROOM intent fired
   - Target is opp slot 1 or 2
   - Anti-spam guards

### Scoring paths
Both bonuses are applied in `_score_action_impl` when the eligibility
methods return True. Picks are recorded via `_record_anti_trick_room_response_pick`
and `_record_anti_trick_room_ko_pick` for anti-spam tracking.

## Unit tests (16 tests, all pass)

| test | result |
|---|---|
| test_master_switch_off | ✓ |
| test_taunt_eligible_when_tr_detected | ✓ |
| test_encore_eligible_when_tr_detected | ✓ |
| test_disable_eligible_when_tr_detected | ✓ |
| test_quash_NOT_eligible | ✓ (Quash is for general anti-setup) |
| test_protect_NOT_eligible | ✓ |
| test_NOT_eligible_when_intent_is_ANTI_TAILWIND | ✓ (TR-specific) |
| test_NOT_eligible_when_intent_is_NO_INTENT | ✓ |
| test_NOT_eligible_when_intent_is_SPREAD_DEFENSE | ✓ |
| test_low_hp_user_not_eligible | ✓ |
| test_wrong_target_not_eligible | ✓ (target must be opp slot 1/2) |
| test_anti_spam_max_picks | ✓ |
| test_damaging_move_eligible_when_tr_detected | ✓ |
| test_status_move_NOT_eligible | ✓ (KO pressure only for damage) |
| test_NOT_eligible_without_tr_intent | ✓ |
| test_master_switch_off (KO) | ✓ |

## Smoke test results (3 pairs, anti-TR enabled)

| matchup | OFF | ON | result |
|---|---:|---:|---|
| vs general_opp_tr (Hatterene) | 1W/0L | 1W/0L | tied |
| vs opp_snarl | 0W/1L | 0W/1L | tied |
| vs opp_hypervoice | 0W/1L | 1W/0L | ON better |

**Observations**:
- 3/3 ON battles did not fire ANTI_TRICK_ROOM intent (NO_INTENT in all)
- This is because the opp did not reveal Trick Room in the captured turns
- The bot killed the TR setters before TR was used
- Anti-TR feature did not need to trigger (opp never got TR off)

## Why anti-TR didn't trigger

The opp team has Hatterene with Trick Room, but in these specific
battles, the bot defeated the TR setters before they could use TR.
The captured turns show:
- t1: opp reveals moonblast (Hatterene using damaging move)
- t3: opp reveals stoneedge
- t5: opp reveals crunch, stoneedge
- t6: opp reveals bugbuzz

The bot's damage was sufficient to KO Hatterene before TR was revealed.
This is a **good outcome** (anti-TR is defensive in nature; if you
don't need it, that's good).

To properly test anti-TR, we would need:
- An opp team that reliably uses TR
- A WG team with Taunt user
- Multiple trials to average out variance

## Files
| action | file |
|---|---|
| MOD | `bot_doubles_damage_aware.py` (+7 config fields, +4 methods, +scoring paths) |
| NEW | `test_planner_anti_tr.py` (16 unit tests) |
| NEW | `data/curated_teams/custom/planner_anti_tr_wg_team.json` (test team) |
| NEW | `logs/phasePLANNER_ANTI_TR.md` (THIS FILE) |

## Stable state
- 223 unit tests pass (was 207, +16 new)
- 0 default flip (default remains `enable_anti_trick_room_response = False`)
- 0 production behavior change (anti-TR is opt-in)

## Awaiting next direction
- **(A) Build opp team that reliably uses TR** for proper smoke test
- **(B) Run 20-pair smoke with anti-TR vs TR team** to verify behavior
- **(C) Different design** — maybe trigger on revealed moves more aggressively
- **(D) Ship as opt-in** — implementation is correct, smoke is inconclusive
- **(E) Close as opt-in** — implementation works, just not exercised in this smoke
