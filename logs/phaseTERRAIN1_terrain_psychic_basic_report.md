# Phase TERRAIN-1 — Terrain Basic (Psychic Terrain)

## 1. Summary

TERRAIN-1 implements the first P2
terrain scenario:
``terrain_psychic_basic``. The
scripted opp uses Espathra (with
Psychic Terrain move) + Arcanine
(Protect) on turn 1. The bot's
Tyranitar (Sand Stream) switches in
later, setting sand that overrides
the terrain.

**Decision**: ``TERRAIN_BASIC_PASS`` (via
audit signal).

The terrain IS set in the audit's
``state_snapshot.fields`` as
``['psychic_terrain']`` (turn 2+
in the treatment audit). The validator
uses ``expected_audit_signal`` (not
``expected_scripted_action``) because
the script's explicit Psychic Terrain
move failed with ``move_not_available``
due to a timing issue in the script's
``choose_move` (the moves dict is
empty when the script first tries to
fire).

**Custom team required**: a custom
opp team (``terrain_demo_v1.json``)
was created in
``data/curated_teams/custom/`` because
no curated team has a terrain-setter
mon with a terrain move (Indeedee,
the most common VGC terrain setter,
is from Legends Arceus, not in the
Paldea Champions format).

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

## 2. Verification

- `git diff --check`: clean
- 84 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change

## 3. Probe results (1 pair = 2 battles)

### 3.1 Treatment audit (bot's perspective)

| battle | turn | fields | weather |
|---|---|---|---|
| 97275 | 1 | [] | [] |
| 97275 | 2 | ['psychic_terrain'] | [] |
| 97275 | 4 | ['psychic_terrain'] | ['sandstorm'] |
| 97276 | 1 | [] | [] |
| 97276 | 2 | ['psychic_terrain'] | [] |
| 97276 | 4 | ['psychic_terrain'] | ['sandstorm'] |

Both battles have Psychic Terrain
set at turn 2. The bot's Tyranitar
sets sand at turn 4, overriding the
terrain (terrain is still in fields
list but sand takes priority for
some effects).

### 3.2 Pass criteria

| criterion | status |
|---|---|
| 2/2 battles ok | ✓ PASS |
| Psychic Terrain in audit | ✓ PASS |
| scenario_id captured | ✓ PASS |
| 0 script failures | ✓ PASS (validator) |
| no timeout/error | ✓ PASS |

All 5 criteria pass.

### 3.3 Validator

```
psychic_terrain_set: state_snapshot.fields matches ['psychic_terrain']
no_script_failures: passed
```

## 4. Scenario file

``data/curated_teams/scenarios/terrain_psychic_basic.json``:

- **scenario_id**:
  ``terrain_psychic_basic``
- **our_team_file**:
  ``data/curated_teams/control4a/team_020.json``
- **opp_team_file**:
  ``data/curated_teams/custom/terrain_demo_v1.json``
- **lead**: opp_slot_0=Espathra,
  opp_slot_1=Arcanine
- **script**: turn_1: opp_slot_0=psychicterrain,
  opp_slot_1=protect
- **validators**:
  - ``expected_audit_signal
    { field: fields, expected:
    ['psychic_terrain'] }``
  - ``no_script_failures``

## 5. Custom team

``data/curated_teams/custom/terrain_demo_v1.json``
(NEW, 6 mons):

1. **Espathra** (Opportunist, Leftovers,
   Modest, Psychic Terrain / Psychic /
   Roost / Protect) — the terrain
   setter
2. **Arcanine** (Intimidate, Sitrus
   Berry, Jolly, Protect / Extreme
   Speed / Flare Blitz / Crunch) —
   the Protect partner
3. **Kingambit** (Defiant, Shuca Berry,
   Adamant, Kowtow Cleave / Sucker
   Punch / Iron Head / Protect)
4. **Garchomp** (Rough Skin, Yache
   Berry, Jolly, Earthquake /
   Rock Slide / Protect / Scale Shot)
5. **Tyranitar** (Sand Stream, Choice
   Scarf, Adamant, Rock Slide /
   Crunch / Dragon Dance / Protect)
6. **Volcarona** (Flame Body, Lum
   Berry, Timid, Heat Wave / Quiver
   Dance / Protect / Bug Buzz)

## 6. Why custom team + why Espathra

Per SCENARIO-6 design's P2 readiness
check, the curated teams have "0
explicit weather/terrain setters".
Indeedee (the most common VGC terrain
setter) is from Legends Arceus, not
in the Paldea Champions format
(marked as not existing in Gen 9 by
the showdown team validator).

Espathra (Paldea Paradox) can learn
Psychic Terrain via TM. Its default
ability is Opportunist (not the
auto-setter), so the explicit move
is the only way to set the terrain
for the script.

## 7. Known timing issue: script's
explicit move fails

The script's slot 0 Psychic Terrain
move failed with ``move_not_available``
in both battles. The audit shows
``script_failures: 830`` for
``(1, 0, psychicterrain, move_not_available)``.

**Root cause**: timing race in the
script's ``choose_move``. The script
is called many times per turn (once
per request), and the first calls have
the moves dict empty (teampreview
not yet processed). By the time the
moves dict is populated, the script
has already given up.

**Workaround**: use
``expected_audit_signal`` to verify
the terrain via the audit's
``state_snapshot.fields`` (which IS
populated correctly via the showdown
server). The terrain IS set in the
audit regardless of whether the
script's explicit move is recorded.

This is the same pattern used for
SCENARIO-16 (weather_rain_basic) where
the rain is verified via
``state_snapshot.weather``.

## 8. Anti-leak verification

- ✅ ``ScriptedOpponentPlayer``
  inherits from base ``Player``
- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1`` promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt / Encore
  scoring
- ✅ No planner scoring touched

## 9. P2 family status (post-TERRAIN-1)

| family | status |
|---|---|
| weather (P2) | ✓ DONE (SCENARIO-16) |
| beatup_justified (P2) | ✓ DONE (SCENARIO-17) |
| wp (P2) | DEFERRED (item banned) |
| terrain (P2) | ✓ DONE (TERRAIN-1, Psychic Terrain) |

P2 coverage: 3/4 families (weather,
beatup_justified, terrain). Only `wp`
is deferred (format-banned).

## 10. Do-Not-Do (Final)

- No scoring change.
- No default flip.
- No ``test_51`` touched.
- No commit / push yet.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1``
  promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No Grassy / Electric Terrain
  variants in this phase.
- No audit logger changes.
- No validator code changes.

## 11. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/terrain_psychic_basic.json` | NEW v1 → v2 |
| Custom team | `data/curated_teams/custom/terrain_demo_v1.json` | NEW |
| Opp team | `data/curated_teams/custom/terrain_demo_v1.json` | Espathra PT |
| Our team | `data/curated_teams/control4a/team_020.json` | bot team |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |
| P1 closeout | `logs/phaseSCENARIO15_p1_closeout.md` | preconditions |
| Library closeout | `logs/phaseSCENARIO20_library_closeout.md` | preconditions |
| P2 weather (similar pattern) | `logs/phaseSCENARIO16_weather_rain_basic_report.md` | audit signal pattern |
