# Phase SCENARIO-15 — P1 Closeout + Library Index

## 1. Summary

SCENARIO-15 is a docs/index-only phase.
It closes out the P1 family of the
scenario library, documents the
current state, and creates a
discoverable index of the scenario
library.

**Decisions**:

- **P1_CLOSE** (3/3 P1 scenarios
  active + 1 deferred + 1 index).
- **NAMING_MISMATCH_NOTED**:
  ``redir_followme_basic`` actually
  scripts Rage Powder, not Follow Me.
  Documented in the index; no rename
  (the family-level name follows
  SCENARIO-6 design).
- **NO_CODE_BEHAVIOR_CHANGE**: no
  audit logger, validator, scenario,
  or scoring change.
- **NO_BATTLE_RUN**: this is a docs
  phase.

**No new code, no new scenario, no
battle run, no commit/push until
user approval** (the user explicitly
asked to commit this).

## 2. Library state

### 2.1 Active scenarios (6)

| # | scenario_id | family | opp lead | scripted move | bot response | status |
|---|---|---|---|---|---|---|
| 1 | `anti_tr_basic` (v6) | anti_tr | Hatterene + Blastoise | Trick Room | Taunt (Zoroark-H) | PASS |
| 2 | `anti_tw_basic` (v2) | anti_tw | Whimsicott + Kingambit | Tailwind | Taunt (Zoroark-H) | PASS |
| 3 | `anti_stat_boost_basic` (v2) | anti_boost | Kingambit + Incineroar | Swords Dance | Taunt (Zoroark-H) | PASS |
| 4 | `spread_def_heat_wave` (v2) | spread_def | Volcarona + Blastoise | Heat Wave | Wide Guard (Torterra) | PASS |
| 5 | `redir_followme_basic` (v2) | redir | Sinistcha + Steelix | **Rage Powder** (not Follow Me) | Heat Wave (Volcarona) | PASS |
| 6 | `spread_def_rock_slide` (v2) | spread_def | Tyranitar + Steelix | Rock Slide | Wide Guard (Torterra) | PASS |

### 2.2 Probes (1)

- `anti_spread_heat_wave_probe.json` (v1):
  pre-library probe (SCENARIO-10A) for
  the Heat Wave + Wide Guard legality
  test. The library entry is
  ``spread_def_heat_wave``.

### 2.3 Deferred scenarios (5)

| family | proposed scenario_id | reason |
|---|---|---|
| spread_def | `spread_def_earthquake` | Earthquake has grounded / Levitate / Flying type detection requirements. Audit logger needs type/ability data. (See `phaseSCENARIO14_earthquake_deferred_report.md`.) |
| redir | `redir_followme` (true Follow Me variant) | Rage Powder covers basic redirection. Follow Me is +0 priority, may be outsped by faster mons. Different script from Rage Powder. |
| beatup_justified | `beatup_justified_basic` | P2 family; only 1 Justified mon in curated teams (Gallade). Needs custom team. |
| wp | `wp_super_effective_basic` | P2 family; 0 Weakness Policy holders in curated teams. Needs custom team. |
| weather | `weather_rain_basic` | P2 family; 0 explicit weather setters in curated teams. Needs custom team. |

## 3. Framework policy (Option C)

- **Canonical signal**: baseline
  audit's ``scripted_actions`` field
  (the scripted opp's perspective).
- **Cross-check**: treatment audit's
  ``opponent_actions.opponent_used_X``
  (the bot's perspective). Diagnostic
  only.
- **Pass condition**: canonical signal
  must have the scripted action with
  ``executed=True``.
- **Gap detection**: if canonical
  fired but treatment didn't confirm,
  set ``bot_opp_action_gap=True`` (no
  fail).
- **Validator**: ``expected_scripted_action``
  type in ``scenario_probe.py``.

### 3.1 Why Option C

The treatment audit's
``opponent_actions`` field is empty
(or ``None``) for scripted scenarios
because the audit logger's
``update_previous_turn`` does not
parse the scripted opp's protocol
events into the bot's
``opponent_actions``. The scripted
opp's protocol events are processed
by the scripted player's own audit,
not the bot's.

The baseline audit's
``scripted_actions`` IS the canonical
record of what the scripted player
did. It is populated by
``ScriptedOpponentPlayer`` and is
always reliable.

### 3.2 Validator types

| type | description |
|---|---|
| `expected_scripted_action` | Option C canonical signal check. **Preferred for scripted scenarios.** |
| `expected_opp_action_used` | Legacy: reads treatment `opponent_actions.opponent_used_X` only. Does not work for scripted scenarios. |
| `expected_audit_signal` | Reads `state_snapshot.X` from the audit. |
| `expected_bot_legal_response` | Reads the bot's `v2l1_legal_action_keys_slotN`. |
| `no_script_failures` | Skeleton. |

## 4. Naming / semantic mismatch

### 4.1 ``redir_followme_basic`` is actually Rage Powder

The scenario file is named
``redir_followme_basic.json`` and
the ``scenario_id`` is
``redir_followme_basic``. The
scripted move is **Rage Powder**,
not Follow Me.

**Why the name mismatch**:
- The SCENARIO-6 design uses
  ``redir_followme_basic`` as a
  family-level name (covers both
  Follow Me and Rage Powder).
- The basic implementation starts
  with Rage Powder (because
  Sinistcha has it; Rage Powder has
  +4 priority vs Follow Me's +0).
- The Follow Me variant would be a
  separate scenario (deferred).

**Why no rename**:
- The family-level name follows
  SCENARIO-6 design.
- The actual move is documented in
  the scenario's ``description``
  field and in the SCENARIO-12
  report.
- The validator's ``field`` is
  ``ragepowder``, not ``followme``,
  so the move semantics are
  unambiguous in the validator.

**Documentation**:
- The mismatch is documented in
  the SCENARIO_INDEX.md (this
  index).
- The SCENARIO-12 report's
  description explicitly says
  "opp scripts Rage Powder".
- The validator's ``name`` is
  ``rage_powder_actually_used``.

**Recommendation**: do NOT rename
the scenario file. Keep the
family-level name. Add the
``redir_followme`` (true Follow Me
variant) as a separate scenario
when implemented.

## 5. Index file

Created
``data/curated_teams/scenarios/SCENARIO_INDEX.md``
with:

- 6 active scenarios with key fields
- 1 probe (SCENARIO-10A)
- 5 deferred scenarios
- Framework policy (Option C)
- Validator types reference
- Usage examples (run scenario,
  validate with Option C, run tests)
- Scenario file format spec
- Move ID normalization rules
- Anti-leak policy
- File map (scenarios + reports)

## 6. Stable state

- 0 scoring change
- 0 default flips
- 0 commit / push yet for
  SCENARIO-15
- 0 model artifacts
- 0 ``test_51`` touched
- 0 RL / V3d.1
- 0 audit logger changes
- 0 validator code changes
- 0 scenario file changes
- 0 test code changes

## 7. Do-Not-Do (Final)

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
- No P2 (Beat Up / WP / weather)
  implementation in this phase.
- No Earthquake (SCENARIO-14)
  implementation in this phase.
- No scenario rename.
- No new scenarios.
- No battle run.

## 8. References

| source | path | role |
|---|---|---|
| Index | `data/curated_teams/scenarios/SCENARIO_INDEX.md` | NEW |
| This report | `logs/phaseSCENARIO15_p1_closeout.md` | NEW |
| P0 closeout | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | P0 closeout |
| P1 review | `logs/phaseSCENARIO11_p1_review_spread_signal_gap_report.md` | policy |
| Option C | `logs/phaseSCENARIO11b_option_c_validator_report.md` | validator |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |
| Scenario files | `data/curated_teams/scenarios/*.json` | library entries |
| Validator | `scenario_probe.py` | framework |

## 9. Final Summary

- **Decision**: ``P1_CLOSE``.
- **Top 5 findings**:
  1. **6 active scenarios** in the
     library: anti_tr_basic,
     anti_tw_basic, anti_stat_boost_basic,
     spread_def_heat_wave,
     redir_followme_basic,
     spread_def_rock_slide.
  2. **1 probe** (SCENARIO-10A) is
     pre-library, kept for
     reproducibility; the library
     entry is `spread_def_heat_wave`.
  3. **5 deferred scenarios**:
     earthquake (framework), Follow
     Me true variant, Beat Up + Justified
     (custom team), WP (custom team),
     weather/terrain (custom team).
  4. **Naming/semantic mismatch
     noted**: `redir_followme_basic`
     actually scripts Rage Powder.
     The family-level name follows
     SCENARIO-6 design. The actual
     move is documented in the
     scenario's `description` and
     the SCENARIO-12 report. The
     validator's `field` is
     `ragepowder`.
  5. **Option C validator
     confirmed as the framework
     policy** for scripted scenarios:
     baseline `scripted_actions` is
     canonical, treatment
     `opponent_actions` is cross-check
     only, gap detection is
     diagnostic.
- **Index created**:
  ``data/curated_teams/scenarios/SCENARIO_INDEX.md``
  lists all scenarios, deferred
  items, framework policy, validator
  types, usage examples, file format
  spec, anti-leak policy, and file
  map.
- **Audit fields sufficient?** YES.
- **Exact next recommended phase**:
  per user's order:
  1. Beat Up + Justified (P2)
  2. Weakness Policy (P2)
  3. Weather/Terrain (P2)
  4. Earthquake (P1, framework
     changes needed)
- **No scoring change. No commit
  yet. No ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
