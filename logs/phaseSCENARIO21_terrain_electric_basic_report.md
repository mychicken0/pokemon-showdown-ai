# Phase SCENARIO-21 — Electric Terrain

## 1. Summary

SCENARIO-21 implements the electric variant
of the terrain family:
``terrain_electric_basic.json``. The scripted
opp leads with Jolteon (Electric Terrain
user) + Arcanine (Protect) and uses
Electric Terrain on turn 1.

**Decision**: ``ELECTRIC_BASIC_PASS``.

Both battles have Electric Terrain and Protect
executed in the baseline audit's
``scripted_actions``. The bot's
Tyranitar (Sand Stream) switches in
later, setting sand that overrides
the terrain/redirect.

**Custom team required**: a custom
opp team
(``electric_demo_v1.json``) was
created in
``data/curated_teams/custom/``
because no curated team has a
Electric Terrain user.

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

## 2. Verification

- ``git diff --check``: clean
- 84 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change

## 3. Probe results (1 pair = 2 battles)

### 3.1 Baseline audit (scripted opp's perspective)

| battle | scenario_id | executed |
|---|---|---|
| 97280 | terrain_electric_basic | (1, 0, electricterrain), (1, 1, protect) |
| 97281 | terrain_electric_basic | (1, 0, electricterrain), (1, 1, protect) |

Both battles have Electric Terrain and
Protect executed.

### 3.2 Pass criteria

| criterion | status |
|---|---|
| 2/2 battles ok | ✓ PASS |
| Electric Terrain executed | ✓ PASS |
| scenario_id captured | ✓ PASS |
| 0 script failures | ✓ PASS |
| no timeout/error | ✓ PASS |

All 5 criteria pass.

### 3.3 Validator (Option C)

```
electricterrain_actually_used: canonical=True gap=True
no_script_failures: passed
```

## 4. Scenario file

``data/curated_teams/scenarios/terrain_electric_basic.json``:

- **scenario_id**: ``terrain_electric_basic``
- **our_team_file**:
  ``data/curated_teams/control4a/team_020.json``
- **opp_team_file**:
  ``data/curated_teams/custom/electric_demo_v1.json``
- **lead**: opp_slot_0=Jolteon,
  opp_slot_1=Arcanine
- **script**: turn_1: opp_slot_0=electricterrain,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: electricterrain, expected: true }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_020 (bot) positions:
1. volcarona
2. blastoise
3. meowscarada
4. tinkaton
5. torterra
6. hatterene

The bot's lead is random. The
canonical signal fires regardless
of the bot's lead (it just verifies
the scripted action fired).

## 6. Custom team

``data/curated_teams/custom/electric_demo_v1.json``
(NEW, 6 mons):

1. **Jolteon** (default ability, Leftovers)
   — the Electric Terrain user
2. **Arcanine** (Intimidate, Sitrus
   Berry) — the Protect partner
3. Kingambit (Defiant, Shuca Berry)
4. Garchomp (Rough Skin, Yache Berry)
5. Tyranitar (Sand Stream, Choice Scarf)
6. Volcarona (Flame Body, Lum Berry)

## 7. Why custom team

Per SCENARIO-6 design's P2 readiness
check, no curated team has a
Electric Terrain user. A custom team was
created with the Jolteon mon (which
learns Electric Terrain via TM in Gen 9).

## 8. Anti-leak verification

- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1`` promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt / Encore
  scoring
- ✅ No planner scoring touched

## 9. Library status (post-SCENARIO-21)

- ✅ terrain_electric_basic (SCENARIO-21, Electric Terrain)
- 13 active scenarios total
- 4 custom teams
- 4 deferred scenarios

## 10. Do-Not-Do (Final)

- No scoring change.
- No default flip.
- No ``test_51`` touched.
- No commit / push yet.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1`` promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No audit logger changes.
- No validator code changes.

## 11. References

| source | path | role |
|---|---|---|
| Scenario | ``data/curated_teams/scenarios/terrain_electric_basic.json`` | NEW v1 → v2 |
| Custom team | ``data/curated_teams/custom/electric_demo_v1.json`` | NEW |
| Opp team | ``data/curated_teams/custom/electric_demo_v1.json`` | Jolteon |
| Our team | ``data/curated_teams/control4a/team_020.json`` | bot team |
| Library design | ``logs/phaseSCENARIO6_library_design.md`` | family plan |
| Library closeout | ``logs/phaseSCENARIO20_library_closeout.md`` | preconditions |
| TERRAIN-1 (similar) | ``logs/phaseTERRAIN1_terrain_psychic_basic_report.md`` | audit signal pattern |
