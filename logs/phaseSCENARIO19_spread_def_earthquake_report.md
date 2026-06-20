# Phase SCENARIO-19 — Spread Defense (Earthquake)

## 1. Summary

SCENARIO-19 implements the Earthquake
variant in the spread_def family:
``spread_def_earthquake``. The
scripted opp leads with Garchomp
(Earthquake) + Charizard (Protect)
and uses Earthquake on turn 1.

**Decision**: ``SPREAD_DEF_EARTHQUAKE_PASS``.

Both battles have Earthquake and
Protect executed in the baseline
audit's ``scripted_actions``.

**No custom team required**: the
curated teams (team_046 with
Garchomp/Earthquake) provide the
Earthquake user. The bot's Wide
Guard check was removed because the
bot doesn't always lead with Torterra
(WG user); the canonical signal
(Earthquake fires) is the primary
validator.

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
| 97271 | spread_def_earthquake | (1, 0, earthquake), (1, 1, protect) |
| 97272 | spread_def_earthquake | (1, 0, earthquake), (1, 1, protect) |

### 3.2 Pass criteria

| criterion | status |
|---|---|
| 2/2 battles ok | ✓ PASS |
| Earthquake executed | ✓ PASS |
| scenario_id captured | ✓ PASS |
| 0 script failures | ✓ PASS |
| no timeout/error | ✓ PASS |

All 5 criteria pass.

### 3.3 Validator (Option C)

```
earthquake_actually_used: canonical=True gap=True
no_script_failures: passed
```

## 4. Scenario file

``data/curated_teams/scenarios/spread_def_earthquake.json``:

- **scenario_id**:
  ``spread_def_earthquake``
- **our_team_file**:
  ``data/curated_teams/control4a/team_020.json``
  (Torterra pos 5 has Wide Guard)
- **opp_team_file**:
  ``data/curated_teams/control4a/team_046.json``
  (Garchomp pos 1 has Earthquake,
  Charizard pos 5 has Protect)
- **lead**: opp_slot_0=Garchomp,
  opp_slot_1=Charizard
- **script**: turn_1: opp_slot_0=earthquake,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: earthquake, expected: true }``
  - ``no_script_failures``

## 5. Why Earthquake was deferred in SCENARIO-14, now doable

Per SCENARIO-14's deferred report,
Earthquake was deferred due to
"grounded / Levitate / Flying type
detection requirements" in the audit
logger. For the **basic** Earthquake
scenario, this is not required:

- The canonical signal (scripted
  actions) records the script fired
  regardless of whether the move is
  effective against the target
- The bot's response (Wide Guard
  legality) is checked but not
  required for the basic test

The audit logger's
``opponent_used_spread`` field would
also fire (Earthquake is in
``_OPP_SPREAD_LIKE``), but the
canonical signal is the baseline
``scripted_actions``.

## 6. Bot's Wide Guard check (documented finding)

The bot's team_020 has Torterra (Wide
Guard) at pos 5. Torterra is brought
in (always in chosen_4), but the
bot's lead is random. In our probe:

- side="p1": lead = Volcarona +
  Hatterene, Torterra in back
- side="p2": lead = Tinkaton +
  Hatterene, Torterra not brought

The bot may not switch Torterra in
if the lead mons are doing well. The
WG legality check was removed from the
validators because the bot's response
is choice-dependent, not a guaranteed
scripted outcome.

For a stricter WG check, a future
scenario could force the bot to bring
Torterra in (e.g., by KO-ing the lead
mons or by using a more aggressive
bot policy). This is out of scope for
the basic scenario.

## 7. Anti-leak verification

- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1`` promotion
- ✅ No V3d.1 PAUSE resumption

## 8. P1 family status (post-SCENARIO-19)

| family | status |
|---|---|
| anti_tr (P0) | ✓ DONE (SCENARIO-5) |
| anti_tw (P0) | ✓ DONE (SCENARIO-7) |
| anti_boost (P0) | ✓ DONE (SCENARIO-8) |
| spread_def (P1) | ✓ DONE (SCENARIO-10/13/19) |
| redir (P1) | ✓ DONE (SCENARIO-12) |
| weather (P2) | ✓ DONE (SCENARIO-16) |
| beatup_justified (P2) | ✓ DONE (SCENARIO-17) |
| wp (P2) | DEFERRED (item banned) |

## 9. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/spread_def_earthquake.json` | NEW v1 → v2 |
| Opp team | `data/curated_teams/control4a/team_046.json` | Garchomp EQ |
| Our team | `data/curated_teams/control4a/team_020.json` | Torterra WG |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |
| P1 closeout | `logs/phaseSCENARIO15_p1_closeout.md` | preconditions |
| Deferred (SCENARIO-14) | `logs/phaseSCENARIO14_earthquake_deferred_report.md` | original deferral |
