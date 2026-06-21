# Phase SCENARIO-20 — Scenario Library Closeout + Index

## 1. Summary

SCENARIO-20 is a docs/index-only phase.
It closes out the scenario library
across P0/P1/P2 (9 active + 1 probe +
4 deferred), documents the banned
items in VGC 2026, and creates a
single source-of-truth index.

**Decision**: ``LIBRARY_CLOSEOUT_DONE``.

The library now has:

- **9 active scenarios** (3 P0 +
  4 P1 + 2 P2)
- **1 probe** (SCENARIO-10A,
  pre-library)
- **4 deferred** scenarios (1 P2
  format-banned, 3 not-started)
- **3 custom teams** (for P2
  scenarios requiring non-curated
  Pokémon)
- **5 banned items** in VGC 2026
  Champions format

**No new code, no new scenario, no
battle run, no commit/push until
user approval**.

## 2. Library state (post-closeout)

### 2.1 Active scenarios (9)

| # | scenario_id | family | P | v | status |
|---|---|---|---|---|---|
| 1 | `anti_tr_basic` | anti_tr | P0 | v6 | PASS |
| 2 | `anti_tw_basic` | anti_tw | P0 | v2 | PASS |
| 3 | `anti_stat_boost_basic` | anti_boost | P0 | v2 | PASS |
| 4 | `spread_def_heat_wave` | spread_def | P1 | v2 | PASS |
| 5 | `redir_followme_basic` | redir | P1 | v2 | PASS |
| 6 | `spread_def_rock_slide` | spread_def | P1 | v2 | PASS |
| 7 | `spread_def_earthquake` | spread_def | P1 | v2 | PASS |
| 8 | `weather_rain_basic` | weather | P2 | v2 | PASS |
| 9 | `beatup_justified_basic` | beatup_justified | P2 | v2 | PASS |

### 2.2 Probes (1)

- `anti_spread_heat_wave_probe.json`:
  pre-library probe (SCENARIO-10A). Uses
  the old `expected_opp_action_used`
  validator. Library entry is
  `spread_def_heat_wave`.

### 2.3 Deferred (4)

| family | reason |
|---|---|
| `wp_super_effective_basic` | **format-banned** (Weakness Policy is `isNonstandard: "Past"` in VGC 2026) |
| `redir_followme` (true variant) | not started (Rage Powder covers basic) |
| `terrain_*_basic` | not started (no terrain-setter mons in curated teams) |
| Earthquake framework-level | superseded by SCENARIO-19 (basic) |

### 2.4 Banned items in VGC 2026 Champions

| item | effect | status |
|---|---|---|
| Weakness Policy | +2 Atk/+2 SpA on super-effective | ✗ PAST |
| Absorb Bulb | +1 SpA on Water hit | ✗ PAST |
| Cell Battery | +1 Atk on Electric hit | ✗ PAST |
| Eject Button | force switch on hit | ✗ PAST |
| Eject Pack | switch on stat drop | ✗ PAST |

These are all marked `isNonstandard:
"Past"` in
`data/mods/champions/items.ts`. The
showdown server explicitly rejects
them with "does not exist in Gen 9"
errors.

**Implication**: any scenario
relying on these items cannot be
tested in VGC 2026 Champions. This
is a real VGC design decision, not
a code limitation.

## 3. Framework policy (Option C)

The library uses **Option C canonical
signal policy**:

- **Canonical signal**: baseline
  audit's ``scripted_actions`` (the
  scripted opp's perspective)
- **Cross-check**: treatment audit's
  ``opponent_actions.opponent_used_X``
  (the bot's perspective). Diagnostic
  only.
- **Pass condition**: canonical signal
  must have the scripted action with
  ``executed=True``
- **Gap detection**: if canonical
  fired but treatment didn't confirm,
  set ``bot_opp_action_gap=True``
  (no fail)

**All 9 active scenarios show**:
canonical=True, treatment=None,
gap=True. This is the **expected
pattern** for scripted scenarios.

## 4. Validator types (5)

| type | purpose | used in |
|---|---|---|
| `expected_scripted_action` | Option C canonical signal | **9 scenarios** |
| `expected_opp_action_used` | legacy, treatment-only | 1 probe (deprecated) |
| `expected_audit_signal` | state_snapshot.X check | weather_rain_basic |
| `expected_bot_legal_response` | bot has move legal | many scenarios |
| `no_script_failures` | skeleton | many scenarios |

## 5. Index file (source of truth)

``data/curated_teams/scenarios/SCENARIO_INDEX.md``
(updated in SCENARIO-20):

- **9 active scenarios** with key
  fields (family, priority, version,
  lead, scripted move, bot response,
  status, report path)
- **1 probe** documented
- **4 deferred** with reasons
- **5 banned items** in VGC 2026
- **3 custom teams** documented
- **Framework policy** (Option C)
- **Validator types** reference
- **Usage** examples (run scenario,
  validate with Option C, run tests)
- **Scenario file format** spec
- **Move ID normalization** rules
- **Anti-leak policy**
- **File map** (scenarios + reports)
- **Version history**
- **Next steps**

## 6. Family coverage

| family | coverage | status |
|---|---|---|
| anti_tr | 1 scenario | ✓ DONE (P0) |
| anti_tw | 1 scenario | ✓ DONE (P0) |
| anti_boost | 1 scenario | ✓ DONE (P0) |
| spread_def | 3 variants (HW, RS, EQ) | ✓ DONE (P1) |
| redir | 1 variant (Rage Powder) | partial (P1) |
| weather | 1 variant (Rain) | ✓ DONE (P2, custom team) |
| beatup_justified | 1 variant (Beat Up) | ✓ DONE (P2, custom team) |
| wp | 0 variants | DEFERRED (format-banned) |
| terrain | 0 variants | DEFERRED (no custom team) |

**Coverage**:
- P0: 3/3 families ✓
- P1: 2/2 families ✓ (spread_def has
  3 variants, redir has 1 variant)
- P2: 2/4 families ✓ (weather,
  beatup_justified); 2 deferred (wp,
  terrain)

## 7. Anti-leak verification

- ✅ Scenarios use scripted opponent
  (inherits from base ``Player``)
- ✅ No scoring change in
  ``bot_doubles_damage_aware.py``
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1``
  promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt / Encore
  scoring
- ✅ No planner scoring touched
- ✅ 84 unit tests pass
- ✅ All 9 active scenarios pass
  with Option C validator
- ✅ No battle run for SCENARIO-20
  (docs only)

## 8. Stable state

- 0 scoring change
- 0 default flips
- 0 commit / push yet for
  SCENARIO-20
- 0 model artifacts
- 0 ``test_51`` touched
- 0 RL / V3d.1
- 0 audit logger changes
- 0 validator code changes
- 0 scenario file changes
- 0 test code changes

## 9. Do-Not-Do (Final)

- No scoring change.
- No default flip.
- No ``test_51`` touched.
- No commit / push until user
  approval.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1``
  promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No TERRAIN-1 implementation in
  this phase.
- No Follow Me true variant in
  this phase.
- No new scenario file in this
  phase.
- No new code change in this phase.

## 10. References

| source | path | role |
|---|---|---|
| Index | `data/curated_teams/scenarios/SCENARIO_INDEX.md` | UPDATED |
| This report | `logs/phaseSCENARIO20_library_closeout.md` | NEW |
| P0 closeout | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | P0 closeout |
| P1 closeout | `logs/phaseSCENARIO15_p1_closeout.md` | P1 closeout |
| Option C | `logs/phaseSCENARIO11b_option_c_validator_report.md` | validator |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |
| All scenario reports | `logs/phaseSCENARIO*.md` | evidence |

## 11. Final Summary

- **Decision**: ``LIBRARY_CLOSEOUT_DONE``.
- **Top 5 findings**:
  1. **9 active scenarios** spanning
     P0 (3 families) + P1 (2 families,
     3 spread_def variants) + P2 (2
     families). 4 deferred. 1 probe
     (pre-library).
  2. **5 items are banned in VGC 2026
     Champions**: Weakness Policy,
     Absorb Bulb, Cell Battery, Eject
     Button, Eject Pack. All marked
     `isNonstandard: "Past"` in the
     showdown mod. The showdown team
     validator explicitly rejects
     them. **This is a real VGC design
     decision, not a code limitation**.
  3. **Option C validator is the
     library's policy**: baseline
     `scripted_actions` is canonical;
     treatment `opponent_actions` is
     cross-check only; gap=True is
     expected for all 9 scenarios.
  4. **3 custom teams created** for
     P2 scenarios: weather_demo_v1
     (Politoed+Rain), beatup_justified_demo_v1
     (Houndoom+Gallade), wp_demo_v1
     (unused, format-banned). All in
     `data/curated_teams/custom/`.
  5. **P1 family (spread_def) has 3
     variants** (Heat Wave, Rock
     Slide, Earthquake) — fully
     covered. P2 has 2 of 4 families
     covered; remaining 2 (wp,
     terrain) are deferred.
- **Audit fields sufficient?** YES
  (via Option C canonical signal).
- **Exact next recommended phase**
  (per user direction):
  1. **TERRAIN-1 — Terrain Basic**
     (P2, field control) — only if
     user wants field control coverage
  2. **PLANNER data generation**
     using existing 9 scenarios as a
     test suite
  3. **Follow Me true variant** —
     additional redir coverage
- **No scoring change. No commit
  yet. No ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
