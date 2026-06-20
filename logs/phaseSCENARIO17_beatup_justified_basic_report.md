# Phase SCENARIO-17 — Beat Up + Justified (Basic)

## 1. Summary

SCENARIO-17 implements the first P2
Beat Up + Justified scenario
(``beatup_justified_basic``). The
scripted opp leads with Houndoom
(Beat Up carrier) + Gallade (Justified
ally) and uses Beat Up on turn 1.
Gallade is brought in as the Justified
ally, ready to be activated by the
bot's Dark-type move.

**Decision**: ``BEATUP_JUSTIFIED_BASIC_PASS``.

Both battles have Beat Up and Protect
executed in the baseline audit's
``scripted_actions``.

**Custom team required**: a custom
opp team
(``beatup_justified_demo_v1.json``)
was created in
``data/curated_teams/custom/`` because:
- No curated team has Beat Up
  (Sneasler, the most common VGC
  Beat Up user, can't learn Beat Up
  in Gen 9)
- Houndoom (Gen 2 Dark/Fire) is the
  Beat Up carrier used

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

## 2. Verification

- `git diff --check`: clean
- 84 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change

## 3. Probe results (1 pair = 2 battles)

### 3.1 Baseline audit (scripted opp's perspective)

| battle | scenario_id | executed |
|---|---|---|
| 97267 | beatup_justified_basic | (1, 0, beatup), (1, 1, protect) |
| 97268 | beatup_justified_basic | (1, 0, beatup), (1, 1, protect) |

Both battles have Beat Up and Protect
executed.

### 3.2 Pass criteria

| criterion | status |
|---|---|
| 2/2 battles ok | ✓ PASS |
| Beat Up executed | ✓ PASS |
| scenario_id captured | ✓ PASS |
| 0 script failures | ✓ PASS |
| no timeout/error | ✓ PASS |

All 5 criteria pass.

### 3.3 Validator (Option C)

```
beat_up_actually_used: canonical=True xcheck=None gap=True
no_script_failures: passed
```

## 4. Scenario file

``data/curated_teams/scenarios/beatup_justified_basic.json``:

- **scenario_id**:
  ``beatup_justified_basic``
- **our_team_file**:
  ``data/curated_teams/control4a/team_020.json``
- **opp_team_file**:
  ``data/curated_teams/custom/beatup_justified_demo_v1.json``
- **lead**: opp_slot_0=Houndoom,
  opp_slot_1=Gallade
- **script**: turn_1: opp_slot_0=beatup,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: beatup, expected: true }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_020 (bot) positions:
1. volcarona
2. blastoise
3. meowscarada
4. tinkaton
5. torterra
6. hatterene

team_057 has Gallade (Justified) at
pos 1, but no Beat Up user. Custom
team with Houndoom (Beat Up) +
Gallade (Justified) was created.

## 6. Custom team

``data/curated_teams/custom/beatup_justified_demo_v1.json``
(NEW, 6 mons):

1. **Houndoom** (Flash Fire, Sitrus
   Berry, Beat Up / Crunch / Protect /
   Fire Fang) — the Beat Up carrier
2. **Gallade** (Justified, Shuca Berry,
   Drain Punch / Zen Headbutt /
   Protect / Bulk Up) — the Justified
   ally
3. Arcanine (Intimidate, Lum Berry,
   Protect / Extreme Speed /
   Flare Blitz / Crunch)
4. Kingambit (Defiant, Leftovers,
   Kowtow Cleave / Sucker Punch /
   Iron Head / Protect)
5. Garchomp (Rough Skin, Yache Berry,
   Earthquake / Rock Slide /
   Protect / Scale Shot)
6. Tyranitar (Sand Stream, Choice
   Scarf, Rock Slide / Crunch /
   Dragon Dance / Protect)

## 7. Why custom team

Per SCENARIO-6 design's P2 readiness
check, no curated team has Beat Up
(the most common VGC user Sneasler
can't learn Beat Up in Gen 9). The
only Justified mon in curated teams
is Gallade (team_057 pos 1). A custom
team was created with Houndoom
(Beat Up carrier) and Gallade (the
Justified ally).

## 8. Anti-leak verification

- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1`` promotion
- ✅ No V3d.1 PAUSE resumption

## 9. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/beatup_justified_basic.json` | NEW v1 → v2 |
| Custom team | `data/curated_teams/custom/beatup_justified_demo_v1.json` | NEW |
| Opp team | `data/curated_teams/custom/beatup_justified_demo_v1.json` | Houndoom + Gallade |
| Our team | `data/curated_teams/control4a/team_020.json` | bot team |
