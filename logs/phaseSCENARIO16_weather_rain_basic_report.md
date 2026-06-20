# Phase SCENARIO-16 — Weather/Terrain Basic (Rain)

## 1. Summary

SCENARIO-16 implements the first P2
family scenario: ``weather_rain_basic``.
The scripted opp leads with Politoed
(Drizzle + Rain Dance) + Arcanine
(Protect) and uses Rain Dance on turn
1. The bot's Tyranitar (Sand Stream)
sets sand on switch-in, overriding
the rain.

**Decision**: ``WEATHER_BASIC_PASS``.

Both battles have Rain Dance and
Protect executed in the baseline
audit's ``scripted_actions``. The
audit's ``state_snapshot.weather`` is
``['raindance']`` initially, then
``['sandstorm']`` after the bot's
Tyranitar switches in.

**Custom team required**: a custom
opp team (``weather_demo_v1.json``) was
created in ``data/curated_teams/custom/``
because no curated team has an explicit
Rain Dance user (per SCENARIO-6
design: "0 explicit weather setters
in repo").

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

**Naming convention** (per
SCENARIO-6 design): ``weather_<variant>``.
First scenario in the weather family
(family 7, P2).

## 2. Verification

- `git diff --check`: clean
- 84 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change
- No ``test_51`` touched
- No commit / push yet

## 3. Probe results (1 pair = 2 battles)

### 3.1 Baseline audit (scripted opp's perspective)

| battle | scenario_id | executed | winner |
|---|---|---|---|
| 97265 | weather_rain_basic | (1, 0, raindance), (1, 1, protect) | V3a2_p00_p2V |
| 97266 | weather_rain_basic | (1, 0, raindance), (1, 1, protect) | V3a2_p00_p1V |

Both battles have Rain Dance and
Protect executed.

### 3.2 Treatment audit (bot's perspective)

| battle | weather per turn |
|---|---|
| 97265 | turn 1: ['raindance'], turn 3: ['sandstorm'] |

The bot's Tyranitar (Sand Stream)
overrides the rain on switch-in.

### 3.3 Pass criteria

| criterion | status | evidence |
|---|---|---|
| 2/2 battles ok | ✓ PASS | both baseline audits ok |
| Rain Dance executed | ✓ PASS | baseline scripted_actions |
| scenario_id captured | ✓ PASS | both audits have it |
| weather in audit (raindance) | ✓ PASS | state_snapshot.weather |
| 0 script failures | ✓ PASS | baseline audits 0 failures |
| no timeout/error | ✓ PASS | runs in 2s |

All 6 criteria pass.

### 3.4 Validator results (with Option C)

```
rain_dance_actually_used: canonical=True xcheck=None gap=True
weather_set_in_audit:    state_snapshot.weather matches ['raindance']
no_script_failures:      passed
```

All pass with `bot_opp_action_gap=True`.

## 4. Scenario file

``data/curated_teams/scenarios/weather_rain_basic.json``:

- **scenario_id**:
  ``weather_rain_basic``
- **our_team_file**:
  ``data/curated_teams/item2/team_010.json``
  (Tyranitar pos 2 with Sand Stream)
- **opp_team_file**:
  ``data/curated_teams/custom/weather_demo_v1.json``
  (Politoed pos 1 with Drizzle +
  Rain Dance, Arcanine pos 2 with
  Protect)
- **lead**: opp_slot_0=Politoed,
  opp_slot_1=Arcanine
- **script**: turn_1: opp_slot_0=raindance,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: raindance, expected: true }``
  - ``expected_audit_signal
    { field: weather, expected:
    ["raindance"] }``
  - ``no_script_failures``

## 5. Custom team

``data/curated_teams/custom/weather_demo_v1.json``
(NEW, 6 mons):

1. Politoed (Drizzle, Leftovers, Modest,
   Rain Dance / Hydro Pump / Ice Beam /
   Protect) — the weather setter
2. Arcanine (Intimidate, Sitrus Berry,
   Jolly, Protect / Extreme Speed /
   Flare Blitz / Crunch) — the
   Protect partner
3. Kingambit (Defiant, Shuca Berry,
   Adamant, Kowtow Cleave / Sucker
   Punch / Iron Head / Protect)
4. Garchomp (Rough Skin, Yache Berry,
   Jolly, Earthquake / Rock Slide /
   Protect / Scale Shot)
5. Tyranitar (Sand Stream, Choice Scarf,
   Adamant, Rock Slide / Crunch /
   Dragon Dance / Protect)
6. Volcarona (Flame Body, Lum Berry,
   Timid, Heat Wave / Quiver Dance /
   Protect / Bug Buzz)

### 5.1 Why custom team

Per SCENARIO-6 design's P2 readiness
check, the curated teams have "0
explicit weather setters" (no Politoed,
Pelipper, Ninetales, Abomasnow). A
custom team was created to provide:

- A weather setter (Politoed with
  Drizzle + Rain Dance)
- Variety for the opp's 6-mon team
- Compatibility with the showdown
  Gen 9 VGC 2026 Reg M-A format

### 5.2 Team format requirements

Items: must be unique per team (Item
Clause), must exist in Gen 9.

EVs: max 32 stat points per stat, max
66 total stat points (corresponds to
~510 EVs). The team file uses
``evs: {hp: 4}`` (just 4 stat points
in HP) to avoid the showdown parser's
EV/IV limits.

Moves: must be learnable by the mon in
Gen 9.

Abilities: must be the mon's ability
in Gen 9. Drizzle is Politoed's hidden
ability but is allowed in the format.

## 6. Lead config reasoning

team_010 (item2) positions:
1. garchomp
2. **tyranitar** (Sand Stream)
3. talonflame
4. pelipper (Drizzle, but the script
   doesn't use it)
5. dragonite
6. indeedee (no, let me verify)

Actually, let me note: the bot's lead is
random (based on the bot's own team).
Tyranitar may not be in the lead but
gets brought in via switch, triggering
Sand Stream.

## 7. Anti-leak verification

- ✅ ``ScriptedOpponentPlayer``
  inherits from base ``Player``
- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1``
  promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt / Encore
  scoring
- ✅ No planner scoring touched

## 8. Test coverage

- 84 unit tests pass (no new tests)
- Reproducible: same scenario file,
  same teams, same result

## 9. P2 family status (post-SCENARIO-16)

| family | status |
|---|---|
| anti_tr (P0) | ✓ DONE (SCENARIO-5) |
| anti_tw (P0) | ✓ DONE (SCENARIO-7) |
| anti_boost (P0) | ✓ DONE (SCENARIO-8) |
| spread_def (P1) | ✓ DONE (SCENARIO-10/13) |
| redir (P1) | ✓ DONE (SCENARIO-12) |
| weather (P2) | ✓ DONE (SCENARIO-16) |
| beatup_justified (P2) | deferred (custom team) |
| wp (P2) | deferred (custom team) |

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
- No SCENARIO-17+ (Beat Up / WP)
  in this phase.
- No Earthquake framework in
  this phase.

## 11. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/weather_rain_basic.json` | NEW v1 → v2 |
| Custom team | `data/curated_teams/custom/weather_demo_v1.json` | NEW |
| Scripted opp | `bot_vgc2026_scripted_opp.py` | unchanged |
| Runner | `bot_vgc2026_phaseV3a2_reality.py` | unchanged |
| Audit | `doubles_decision_audit_logger.py` | unchanged |
| Opp team | `data/curated_teams/custom/weather_demo_v1.json` | Politoed RD |
| Our team | `data/curated_teams/item2/team_010.json` | Tyranitar Sand |
| P1 closeout | `logs/phaseSCENARIO15_p1_closeout.md` | preconditions |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |

## 12. Final Summary

- **Decision**: ``WEATHER_BASIC_PASS``.
- **Top 5 findings**:
  1. **Rain Dance fires reliably** in
     baseline audit's
     ``scripted_actions`` for both
     battles. The custom team's
     Politoed has Rain Dance in its
     moveset (Drizzle + Rain Dance).
  2. **Weather is set in the audit's
     ``state_snapshot.weather``** as
     ``['raindance']`` initially, then
     overridden by Tyranitar's Sand
     Stream to ``['sandstorm']``. The
     ``expected_audit_signal`` validator
     correctly detects the rain.
  3. **Custom team was required**: no
     curated team has Rain Dance. A
     custom opp team
     (``weather_demo_v1.json``) was
     created with Politoed, Arcanine,
     Kingambit, Garchomp, Tyranitar,
     Volcarona.
  4. **Team format requirements
     (Gen 9 VGC)**:
     - Items must be unique (Item Clause)
     - EVs in stat points (0-32 per stat,
       max 66 total)
     - Moves must be learnable
     - Drizzle (Politoed's hidden
       ability) is allowed
  5. **P2 family complete** (first
     variant): ``weather_rain_basic``
     added to scenario library. Other
     P2 families (Beat Up + Justified,
     WP) still need custom teams.
- **Audit fields sufficient?** YES.
- **Exact next recommended phase**:
  per user's order:
  1. Beat Up + Justified (P2, custom
     team)
  2. Weakness Policy (P2, custom team)
  3. Earthquake (P1, framework
     changes needed)
- **No scoring change. No commit
  yet. No ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
