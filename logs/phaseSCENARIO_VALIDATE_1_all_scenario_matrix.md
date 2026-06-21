# Phase SCENARIO-VALIDATE-1 — All-Scenario Validation Matrix

## 1. Summary

SCENARIO-VALIDATE-1 produces a single
validation matrix for all 13 active
scenarios in the library, after the
TERRAIN-2A cleanup. The matrix
confirms:

- **13/13 PASS** (no FAIL, no NO-AUDIT)
- **All 13 use `expected_scripted_action`**
  (canonical=True, gap=True)
- The `expected_audit_signal` approach
  is **no longer used** for any active
  scenario (the cleanup removed the
  Psychic Terrain exception)

**Decision**: `LIBRARY_CLEAN_DONE` —
all 13 scenarios are clean with the
same canonical signal pattern.

## 2. Validation matrix

| # | scenario_id | family | P | canonical | gap | pass | type |
|---|---|---|---|---|---|---|---|
| 1 | `anti_tr_basic` | anti_tr | P0 | True | True | ✓ | `expected_scripted_action` |
| 2 | `anti_tw_basic` | anti_tw | P0 | True | True | ✓ | `expected_scripted_action` |
| 3 | `anti_stat_boost_basic` | anti_boost | P0 | True | True | ✓ | `expected_scripted_action` |
| 4 | `spread_def_heat_wave` | spread_def | P1 | True | True | ✓ | `expected_scripted_action` |
| 5 | `redir_followme_basic` | redir | P1 | True | True | ✓ | `expected_scripted_action` |
| 6 | `spread_def_rock_slide` | spread_def | P1 | True | True | ✓ | `expected_scripted_action` |
| 7 | `spread_def_earthquake` | spread_def | P1 | True | True | ✓ | `expected_scripted_action` |
| 8 | `weather_rain_basic` | weather | P2 | True | True | ✓ | `expected_scripted_action` |
| 9 | `beatup_justified_basic` | beatup_justified | P2 | True | True | ✓ | `expected_scripted_action` |
| 10 | `terrain_psychic_basic` | terrain | P2 | True | True | ✓ | `expected_scripted_action` |
| 11 | `terrain_electric_basic` | terrain | P2 | True | True | ✓ | `expected_scripted_action` |
| 12 | `terrain_grassy_basic` | terrain | P2 | True | True | ✓ | `expected_scripted_action` |
| 13 | `redir_followme_true_basic` | redir | P1 | True | True | ✓ | `expected_scripted_action` |

**Summary**: 13 PASS, 0 FAIL, 0 NO-AUDIT
(out of 13)

## 3. Family coverage

| family | scenarios | priority | coverage |
|---|---|---|---|
| anti_tr | 1 | P0 | ✓ full |
| anti_tw | 1 | P0 | ✓ full |
| anti_boost | 1 | P0 | ✓ full |
| spread_def | 3 (HW, RS, EQ) | P1 | ✓ 3 variants |
| redir | 2 (Rage Powder, Follow Me) | P1 | ✓ 2 variants |
| weather | 1 | P2 | ✓ 1 variant |
| beatup_justified | 1 | P2 | ✓ 1 variant |
| terrain | 3 (Psychic, Electric, Grassy) | P2 | ✓ 3 variants |
| wp | 0 | P2 | ✗ DEFERRED (format-banned) |

**8/9 families covered** (only `wp` deferred)

## 4. Per-priority summary

| priority | count | families |
|---|---|---|
| P0 | 3 | anti_tr, anti_tw, anti_boost |
| P1 | 5 | spread_def ×3, redir ×2 |
| P2 | 5 | weather, beatup_justified, terrain ×3 |
| **Total** | **13** | **8 families** |

## 5. Validator type consistency

**All 13 scenarios use
`expected_scripted_action`** as the
canonical signal validator. This is
the preferred pattern per the Option C
framework policy.

No scenarios use
`expected_audit_signal` anymore
(TERRAIN-2A removed the last
exception).

No scenarios use
`expected_opp_action_used` (the old
legacy validator from the probe).

## 6. Cross-check pattern (gap=True)

All 13 scenarios show
`bot_opp_action_gap=True` — this is
the **expected pattern** for scripted
scenarios. The treatment audit's
`opponent_actions` field is empty (or
None) for scripted scenarios because
the audit logger's `update_previous_turn`
does not parse the scripted opp's
protocol events into the bot's
`opponent_actions`.

The canonical signal
(`scripted_actions` in the baseline
audit) IS the authoritative record.

## 7. Deferred / banned (4)

| family | scenario | reason |
|---|---|---|
| wp | `wp_super_effective_basic` | Weakness Policy is `isNonstandard: "Past"` in VGC 2026 Champions |
| terrain | Misty Terrain variant | No Paldea mon with Misty Terrain in champions learnsets |
| redir | (full Follow Me with Indeedee) | Indeedee from Legends Arceus, not in Paldea |
| (spread_def) | (Earthquake framework-level) | superseded by basic Earthquake (SCENARIO-19) |

The `wp_super_effective_basic` scenario
file is in the library but marked
DEFERRED in the description.

## 8. Custom teams (7)

All 7 custom teams are in
`data/curated_teams/custom/`:

| file | setter | event |
|---|---|---|
| `weather_demo_v1.json` | Politoed | SCENARIO-16 |
| `beatup_justified_demo_v1.json` | Houndoom | SCENARIO-17 |
| `wp_demo_v1.json` | Dragonite (WP) | SCENARIO-18 (DEFERRED) |
| `terrain_demo_v1.json` | Espathra | TERRAIN-1, TERRAIN-2A |
| `electric_demo_v1.json` | Jolteon | SCENARIO-21 |
| `grassy_demo_v1.json` | Tsareena | SCENARIO-22 |
| `followme_demo_v1.json` | Clefable | SCENARIO-23 |

## 9. Banned items in VGC 2026 (5)

| item | effect |
|---|---|
| Weakness Policy | +2 Atk/+2 SpA on super-effective |
| Absorb Bulb | +1 SpA on Water |
| Cell Battery | +1 Atk on Electric |
| Eject Button | force switch on hit |
| Eject Pack | switch on stat drop |

All marked `isNonstandard: "Past"` in
`data/mods/champions/items.ts`.

## 10. Top findings

1. **All 13 scenarios PASS** with
   the same canonical signal pattern
2. **TERRAIN-2A cleanup was critical**:
   the Psychic Terrain lead/species
   mismatch was masking the canonical
   signal. After fixing the lead to
   Espathra (the actual setter), the
   canonical signal works
3. **No more `expected_audit_signal`
   exceptions**: the cleanup removed
   the last exception
4. **All canonical=True, gap=True**:
   the cross-check pattern is consistent
5. **8/9 families covered**: only `wp`
   is deferred (format-banned)

## 11. References

| source | path | role |
|---|---|---|
| Cleanup | `logs/phaseTERRAIN2A_psychic_terrain_cleanup_report.md` | TERRAIN-2A fix |
| Library | `data/curated_teams/scenarios/SCENARIO_INDEX.md` | index file |
| Validators | `scenario_probe.py` | `run_validators_with_canonical` |
| This report | `logs/phaseSCENARIO_VALIDATE_1_all_scenario_matrix.md` | NEW |
