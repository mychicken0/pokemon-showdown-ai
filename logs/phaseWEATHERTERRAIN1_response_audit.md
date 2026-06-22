# Phase WEATHER-TERRAIN-1 — Weather/Terrain Response Audit

**Date**: 2026-06-22
**Status**: `SWITCH_SCORING_GAP`
**Phase**: WT-1 (read-only audit)

## Summary

The bot detects weather/terrain states in audit data but does
not respond to them with control moves or type-boost scoring.
Counterplay is switch-based (switch to weather resist or Drizzle
user), not move-based.

## Questions answered

### Q1. Does audit state_snapshot persist weather and terrain fields clearly?

**YES** (with caveats):
- `state_snapshot.weather` contains weather list (e.g., `['raindance']`)
- `state_snapshot.fields` contains terrain list (e.g., `['psychic_terrain']`)
- Both are JSON-safe lists of strings
- Found in existing audits: TERRAIN1 v3, SCENARIO16 weather, PLANNER-SPREAD-9 rain

### Q2. In weather/terrain scenarios, does the bot detect the field state?

**YES**:
- `state_snapshot.weather` is populated correctly
- `state_snapshot.fields` is populated correctly
- The bot's Psychic Terrain priority-block detection works
  (`priority_blocked_by_psychic_terrain` reason)
- Found: bot detects terrain in TERRAIN1 v3 audit (`fields=['psychic_terrain']`)
- Found: bot detects weather in PLANNER-SPREAD-9 audit (`weather=['raindance']`)

### Q3. When opponent sets Rain/Sun/Terrain, what does bot select next?

**Examples from audit data**:

In **PLANNER-SPREAD-9** (rain opp, turn 3-5):
- t3: bot selects `rockslide, protect` (damage + Protect)
- t4: bot switches `Pelipper` in (Drizzle user)
- t5: bot selects `protect, hurricane 1` (Protect + water move boosted by rain)

In **TERRAIN1 v3** (Psychic Terrain opp, turn 2-4):
- t2: bot selects `heatwave, dazzlinggleam` (spread damage)
- t3: bot selects `heatwave, psychic 1` (Psychic move boosted by terrain)
- t4: bot switches `Blastoise, Torterra` in (resists Psychic Terrain?)

The bot's response:
1. **Switch to mon that resists the weather/terrain**
2. **Use Protect/stall while waiting**
3. **Use type-matching moves** (Hurricane in rain, Psychic in Psychic Terrain)

### Q4. Does bot have legal counterplay available?

**Depends on team's moveset**:
- In TERRAIN1 audit: bot's legal actions do NOT include any weather/terrain control moves
- In PLANNER-SPREAD-9: bot switches to Pelipper (Drizzle user)
- Bot's counterplay is always **switch-based**, never **move-based**

Available counterplay types (per user spec):
- weather move: NOT in legal options (bot doesn't have Sunny Day/Rain Dance on active)
- terrain move: NOT in legal options (bot doesn't have terrain setter on active)
- switch to better resist/ability: YES (e.g., switch to Pelipper for rain, switch to water-type for sandstorm)
- Protect/stall: YES (Protect is always available)
- KO setter: YES (damage moves are available)

### Q5. Does bot ever choose weather/terrain control moves naturally?

**NO**:
- In TERRAIN1 audit (4 turns of legal actions), no weather/terrain moves selected
- In PLANNER-SPREAD-9 rain audit, no weather/terrain moves selected
- Bot always chooses: damage moves, Protect, or switches

### Q6. If not, are their raw scores 0/negative like setup/status moves?

**CANNOT VERIFY** directly:
- Raw scores are NOT captured in the current audit
- `v4a_raw_scores_slot0` and `v4a_raw_scores_slot1` are `None`
- Cannot inspect raw scoring for weather/terrain control moves

**Inference**:
- Weather/terrain control moves are setup moves
- Setup moves typically score 0 by default (no damage)
- Bot's setup bonus (anti_setup_disruption) is for DISRUPTING setup, not creating it
- No specific weather/terrain bonus exists in the bot

### Q7. Is the missing piece move scoring or switch scoring?

**Switch scoring**:
- Bot already switches to handle weather/terrain (e.g., switch to Pelipper)
- Bot already has the legal switch options
- The MISSING piece is **scoring** the switch's value in weather/terrain terms
- Currently: switch is scored by type matchup and stats, not by weather/terrain synergy

**Move scoring gap (secondary)**:
- No weather/terrain type-boost scoring (Rain boosts Water 1.5x)
- No weather/terrain setter bonus (setter mon gets a small bonus)
- These would help when the bot HAS a weather/terrain setter on the bench

### Q8. Are weather/terrain responses blocked by lack of audit fields?

**NO** (audit is sufficient):
- `state_snapshot.weather` and `state_snapshot.fields` are present
- `v4a_legal_action_keys_slot0/1` show available moves
- The missing piece is in the SCORING, not in the AUDIT

## Inspect findings

### Audit structure (sufficient)
- `state_snapshot.weather`: list of weather IDs
- `state_snapshot.fields`: list of terrain IDs
- `v4a_legal_action_keys_slot0/1`: per-slot legal actions
- `opponent_actives_state`: per-opp-mon state (species, ability, etc.)
- `selected_joint_order`: bot's actual selection

### What's missing in audit
- `v4a_raw_scores_slot0/1`: None in current audits (would help debug scoring)
- No terrain-extender items tracking
- No weather-extender items tracking
- No weather-rock items tracking (e.g., Damp Rock, Heat Rock)

### Existing relevant scoring
- Psychic Terrain priority block: ✓ detected (reason code stored)
- Speed priority threats: tracked per slot
- Expected damage: tracked per opp slot

### What's NOT in scoring
- Type boost from weather (Rain 1.5x Water)
- Type boost from terrain (Psychic Terrain 1.5x Psychic)
- Weather setter bonus (Politoed w/ Drizzle gets bonus for rain up)
- Terrain setter bonus (Indeedee-F gets bonus for Psychic Terrain up)
- Weather extender bonus (Damp Rock extends rain from 5 to 8 turns)
- Terrain extender bonus (Terrain Extender extends terrain from 5 to 8 turns)

## Decision: `SWITCH_SCORING_GAP`

The bot's weather/terrain response is fundamentally a **switch
scoring gap**, not a move scoring gap:

1. **Audit is sufficient**: state_snapshot.weather and fields are captured
2. **Legal actions captured**: v4a_legal_action_keys shows available moves
3. **Switch logic exists**: bot does switch to handle weather/terrain
4. **Switch scoring is missing**: bot doesn't value switching to a
   weather/terrain-resist mon more than switching to a damage mon

### Secondary move scoring gap (related):
- No type-boost scoring for weather/terrain conditions
- Bot's legal actions in terrain scenarios don't include terrain setters
- Even if bot had a terrain setter, there's no bonus for using it

### Why this matters:
- In VGC, weather/terrain control is a key strategic axis
- Politoed (Drizzle) is one of the most-used mons in VGC 2024
- Indeedee-F (Psychic Surge) is a top support mon
- Bot's lack of weather/terrain response is a competitive disadvantage

## Path forward (deferred)

1. **Switch scoring for weather/terrain**: add switch bonus for
   mon that resist the active weather/terrain (or has the setter ability)
2. **Move scoring for weather boost**: add damage multiplier for
   weather/terrain type boosts (e.g., Rain active + Water move = +50%)
3. **Move scoring for weather/terrain setters**: add bonus for
   using Rain Dance, Sunny Day, terrain setters (similar to
   anti-TR bonus logic)

These are independent features. Each would have its own phase:
- Phase WT-2: switch scoring for weather/terrain
- Phase WT-3: move scoring for type boosts
- Phase WT-4: move scoring for weather/terrain setters

## Files

### Modified
- (none — read-only audit)

### New
- `logs/phaseWEATHERTERRAIN1_response_audit.md` (this file)

### Referenced
- `logs/vgc2026_phaseTERRAIN1_v3_treatment_audit.jsonl` (terrain audit)
- `logs/vgc2026_phasePLANNER_SPREAD_9_general_*_rain_*_treatment_audit.jsonl` (rain audit)
- `logs/phaseTERRAIN1_terrain_psychic_basic_report.md` (terrain report)
- `logs/phaseSCENARIO16_weather_rain_basic_report.md` (weather report)
- `logs/phaseSCENARIO21_terrain_electric_basic_report.md` (electric terrain report)
- `logs/phaseSCENARIO22_terrain_grassy_basic_report.md` (grassy terrain report)

## Stable state
- 0 code changes (audit only)
- 0 default flip
- 0 magnitude tuning
- 132 related tests pass
- Weather/terrain response stays OPT_IN / UNIMPLEMENTED
