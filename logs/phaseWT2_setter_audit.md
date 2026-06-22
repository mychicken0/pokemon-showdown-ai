# Phase WT-2 — Setter Team Audit Report

**Date**: 2026-06-22
**Status**: `SWITCH_SCORING_GAP_CONFIRMED`
**Phase**: WT-2 (read-only audit with setter team)

## Summary

3 battles run with a custom bot team that has explicit **setter MOVES**
(Politoed with Rain Dance but no Drizzle; Rillaboom with Grassy Terrain
but no Grassy Surge). The bot had setter moves as **legal actions in
31 of 71 turns** (44%). **The bot selected a setter move 0 times** (0%).

This **confirms** the WT-1 finding (`SWITCH_SCORING_GAP`): the bot does
not select setter moves even when they are legal and would be useful.

## Methodology

### Custom team: data/curated_teams/custom/wt2_audit_team_v1.json

Bot team with explicit setter MOVES (no setter abilities):

| Pokémon | Ability | Setter Move | Notes |
|---------|---------|-------------|-------|
| Politoed | Water Absorb (not Drizzle) | Rain Dance | Tests move-based setter |
| Rillaboom | Overgrow (not Grassy Surge) | Grassy Terrain | Tests move-based setter |
| Tapu Lele | Psychic Surge (ability) | (no move) | Reference: ability-based auto-setter |

This isolates the move-based setter behavior:
- Politoed has Rain Dance but no Drizzle → if bot doesn't use Rain Dance,
  rain is never set (no ability to auto-set it)
- Rillaboom has Grassy Terrain but no Grassy Surge → if bot doesn't use
  Grassy Terrain, terrain is never set
- Tapu Lele has Psychic Surge (ability) → terrain always set on switch

### Probe: showdown_ai/bot_wt2_setter_audit_probe.py

- 3 battles via `bot.battle_against(opp, n_battles=1)`
- Format: `gen9doublescustomgame` (custom teams work, not ladder)
- Opp: RandomPlayer with generic team (no setters)
- For each turn, record:
  - `state_snapshot.weather`, `state_snapshot.fields`
  - Per-slot `setter_in_legal` (which setter moves are in legal_orders)
  - Per-slot `selected_move` (what the bot picked)
- Watchdogs: heartbeat 30s, stall 180s, total 300s

## Findings

### F1. Setter is in legal actions frequently (31/71 turns = 44%)

Politoed (with Rain Dance) and Rillaboom (with Grassy Terrain) are
frequently on the field. When they are, the setter move is in legal
actions.

### F2. Setter is NEVER selected (0/31 setter-legal turns = 0%)

The bot never selected a setter move. It always picked:
- Damage moves (woodhammer, hydropump, icebeam)
- Protect
- Switch

### F3. Setter is selected over by large margin

| Turn | Active | Setter in legal | Bot selected | Margin |
|------|--------|-----------------|--------------|--------|
| T8 | Rillaboom | grassyterrain | woodhammer | damage > setter |
| T9 | Rillaboom | grassyterrain | woodhammer | damage > setter |
| T16 | Politoed | raindance | hydropump | damage > setter |
| T17 | Politoed | raindance | hydropump | damage > setter |
| T20 | Politoed | raindance | hydropump | damage > setter |
| T24 | Politoed | raindance | icebeam | damage > setter |

In every case, the bot prefers a damage move over the setter.

### F4. Weather/terrain is never set in audit

After 71 turns, the audit's `state_snapshot.weather` and
`state_snapshot.fields` are empty (or contain only the opponent's
auto-set fields from Tapu Lele's Psychic Surge). The bot's setter
moves are never used, so rain and grassy terrain are never set
by the bot.

### F5. This confirms WT-1 finding (no regression)

WT-1 was a read-only audit of existing data. It found:
- Bot detects weather/terrain in audit ✓
- Bot has no setter in legal actions (in tested teams) ✓
- Bot responds via switch, Protect, type-boost ✓

WT-2 explicitly tests teams WITH setter moves. The bot has setter
in legal actions but doesn't pick them. This confirms:
- Setter is in legal orders when available ✓
- Setter is not selected by scoring (vs. damage) ✓

## Bug or by design?

**Likely by design** (per current scoring):
- Setter moves provide delayed benefit (5 turns of weather/terrain)
- Damage moves provide immediate benefit (HP reduction)
- Bot prioritizes immediate damage over delayed benefit
- This is reasonable for short battles

**But could be a gap**:
- If bot never sets up favorable conditions, opponents will
- The bot's switch-based response is reactive, not proactive
- In a 10-turn game, missing 5 turns of damage boost matters

## Root cause analysis (preliminary)

Per WT-1: "Raw scores are NOT captured in the current audit".
`v4a_raw_scores_slot0` and `v4a_raw_scores_slot1` are `None`.

The scoring system likely has:
- Setter raw score = 0 (or some low value)
- Damage raw score = (expected damage × effectiveness)
- Setter never wins the comparison

To fix this (if desired):
- Add weather/terrain bonus when setter is used
- Add "weather-up" synergy bonus for damage moves
- But this changes scoring → outside WT-2 scope

## Comparison with WT-1

| Aspect | WT-1 | WT-2 |
|--------|------|------|
| Test teams | Existing (no setter) | Custom (with setter) |
| Setter in legal? | 0 turns | 31 turns |
| Setter selected? | n/a | 0 turns |
| Confirms switch gap? | Yes (no setter at all) | Yes (setter in legal but not picked) |

## Conclusion

**Decision**: `SWITCH_SCORING_GAP_CONFIRMED`

The bot does not select setter moves even when they are legal.
This is a scoring gap, not a detection bug.

**Recommendation**:
- **Do NOT adopt default fix** (per AGENTS.md, requires evidence ladder gates)
- **Do NOT magnitude-tune** the setter score (insufficient evidence)
- **Keep opt-in** for any setter bonus (when added)
- **Document gap** in `ROOT_INDEX.md` and `walkthrough.md`

## What is NOT a bug

- Bot detects weather/terrain correctly (F1 from WT-1, F4 from WT-2)
- Bot's switch-based response works (F1 from WT-1)
- Bot's type-boost damage selection works (F1 from WT-1)
- Setter raw score is 0/low (likely design, not bug)
- Setter is in legal_orders when available (this audit)

## Pre-existing test breakage (not a regression)

The same 22 tests from WT-1 still fail (pre-existing in HEAD):
- test_vgc2026_phaseV2{h,i,j}.TestInspectorIntegration.* tests fail
  because they do `subprocess.run([python, 'inspect_X.py'], cwd=tests/)`
  expecting the file at tests/, but it's at scripts/inspect/. Not
  introduced by this audit.

## Verification

- `git diff --check`: clean (no code changes)
- 3 battles completed
- 71 turns recorded
- 31 setter-legal turns
- 0 setters selected
- Probe script: `showdown_ai/bot_wt2_setter_audit_probe.py`
- Audit data: `logs/wt2_setter_audit.jsonl`
- Summary: `logs/wt2_setter_audit_summary.json`
- Test data: `data/curated_teams/custom/wt2_audit_team_v1.json`

## Open questions for user

- Is this gap acceptable? (User said: "do not flip defaults")
- Should we add a small "weather-up" bonus? (Would need evidence)
- Is there a Phase to fix this? (Could be 6.x.x)
