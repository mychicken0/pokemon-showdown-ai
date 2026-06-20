# Phase SCENARIO-10 — Spread Defense Basic (Heat Wave + Wide Guard)

## 1. Summary

SCENARIO-10 implements the first
P1 family scenario: spread defense
via Heat Wave + Wide Guard. Per the
SCENARIO-6 design's spread_def family,
this is the "basic" Heat Wave variant.
Rock Slide and Earthquake variants are
deferred to SCENARIO-10b / 10c (separate
phases).

**Decision**: `SPREAD_DEF_BASIC_PASS`.

The canonical signal (baseline audit's
``scripted_actions``) confirms Heat
Wave fires in both battles. Wide
Guard is legal in the bot's audit at
turns 3, 4, 5 (Araquanid brought in).
The bot's lead is random (Gallade +
Tsareena) but Araquanid is in the
back, brought in via switch.

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

**Naming convention** (per
SCENARIO-6 design): ``spread_def_<variant>``.
This is the first scenario using the
``spread_def`` family prefix (P0 used
``anti_tr`` / ``anti_tw`` / ``anti_boost``).
Future P1 variants: ``spread_def_rock_slide``,
``spread_def_earthquake``.

## 2. Verification

- `git diff --check`: clean
- 68 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change
- No ``test_51`` touched
- No commit / push yet

## 3. Probe results (1 pair = 2 battles)

### 3.1 Baseline audit (scripted opp's perspective)

| battle | scenario_id | executed | failures |
|---|---|---|---|
| 97255 | spread_def_heat_wave | (1, 0, heatwave), (1, 1, protect) | 0 |
| 97256 | spread_def_heat_wave | (1, 0, heatwave), (1, 1, protect) | 0 |

Both battles have Heat Wave and
Protect executed in the baseline
audit's ``scripted_actions`` (the
canonical signal).

### 3.2 Treatment audit (bot's perspective)

| battle | audit_turns | opp_actions.spread | WG legal |
|---|---|---|---|
| 97255 | 8 turns | empty (gap) | turns 3, 4, 5 (slot 1) |

The bot's audit's
``opponent_actions.opponent_used_spread``
field is empty (known framework gap
per SCENARIO-6 design). The bot's
audit's ``v2l1_legal_action_keys_slotN``
field correctly shows Wide Guard
legal at turns 3, 4, 5 (Araquanid
in active slot).

### 3.3 Pass criteria

| criterion | status | evidence |
|---|---|---|
| 2/2 battles ok | ✓ PASS | both baseline audits ok |
| Heat Wave executed in both | ✓ PASS | baseline scripted_actions |
| spread audit equivalent fires | ✓ PASS | scripted_actions has heatwave |
| WG legal in some audited turn | ✓ PASS | turns 3, 4, 5 |
| scenario_id captured | ✓ PASS | both audits have it |
| 0 script failures | ✓ PASS | both baseline audits 0 |
| no timeout/error | ✓ PASS | runs in 2s |

All 7 criteria pass.

### 3.4 Framework gap (documented)

The bot's audit's
``opponent_actions.opponent_used_spread``
field is **not populated** for the
scripted opp's Heat Wave. This is a
known framework gap (per SCENARIO-6
design): the audit logger's turn_events
parser does not capture the scripted
opp's moves in ``opponent_actions``
because the protocol events for the
scripted opp are processed by the
scripted player's audit (baseline),
not the bot's audit (treatment).

**Workaround**: use the baseline
audit's ``scripted_actions`` as the
canonical signal for scripted moves.
This is the same pattern as
SCENARIO-5/7/8 (TR/TW/SD) and
SCENARIO-10A (probe).

The ``expected_bot_legal_response``
validator works correctly because
it reads the bot's audit's
``v2l1_legal_action_keys_slotN`` field,
which IS populated.

## 4. Scenario file

``data/curated_teams/scenarios/spread_def_heat_wave.json``:

- **scenario_id**:
  ``spread_def_heat_wave``
- **our_team_file**: team_057
  (Araquanid at pos 2 has Wide Guard;
  Gallade, Kangaskhan, Tsareena,
  Chandelure, Goodra-H at other
  positions)
- **opp_team_file**: team_020
  (Volcarona at pos 1 has Heat Wave;
  Blastoise at pos 2 has Protect;
  Torterra at pos 5 has Wide Guard;
  Hatterene, Meowscarada, Tinkaton
  at other positions)
- **lead**: opp_slot_0=Volcarona,
  opp_slot_1=Blastoise
- **script**: turn_1: opp_slot_0=heatwave,
  opp_slot_1=protect
- **validators**:
  - ``expected_opp_action_used { field:
    spread, expected: true }``
  - ``expected_bot_legal_response
    { expected: "Wide Guard" }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_020 positions:
1. **volcarona** (Heat Wave, Protect,
   Giga Drain, Quiver Dance)
2. **blastoise** (Protect, Fake Out,
   Water Pulse, Ice Beam)
3. meowscarada
4. tinkaton
5. torterra (Wide Guard)
6. hatterene

team_057 positions:
1. gallade
2. **araquanid** (Wide Guard)
3. kangaskhan
4. tsareena
5. chandelure
6. goodrahisui

Lead with Volcarona (pos 1) +
Blastoise (pos 2). Both have Protect.
Volcarona fires Heat Wave (all
adjacent foes), Blastoise Protects.

Araquanid is in team_057 at pos 2.
The bot's lead is random; Araquanid
is brought in later. WG becomes
legal at turn 3+.

## 6. Comparison to SCENARIO-10A probe

SCENARIO-10 is the same as the
SCENARIO-10A probe but:
- Filename: ``spread_def_heat_wave.json``
  (matches SCENARIO-6 family naming).
- scenario_id: ``spread_def_heat_wave``
  (matches family naming).
- No "_probe" suffix (full scenario,
  not a probe).

Same teams (team_020 opp, team_057
our), same lead config, same script.
The probe (SCENARIO-10A) confirmed
the framework works; SCENARIO-10
adds it to the scenario library.

## 7. Anti-leak verification

- ✅ ``ScriptedOpponentPlayer`` inherits
  from base ``Player`` (not bot)
- ✅ Module has no import of
  ``DoublesDamageAwareConfig``,
  ``DoublesDamageAwarePlayer``, or
  ``score_action``
- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1`` promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard scoring added
- ✅ No planner scoring touched

## 8. Test coverage

- 68 unit tests pass (no new tests
  added; the scenario is a runtime
  evidence, not a fixture test).
- The scenario is reproducible: same
  scenario file, same teams, same
  result.

## 9. P1 readiness update

Per SCENARIO-9 readiness criteria,
P1 implementation requires:
- 3/3 P0 scenarios pass ✓
- 0 meaningful script failures ✓
- Lead config honored for
  non-overlapping teams ✓
- /team format pinned by unit test ✓
- 67+ unit tests pass ✓

**Plus SCENARIO-10A probe gate**:
1-pair spread probe passes without
code changes. ✓

All gates met. P1 implementation
proceeds with SCENARIO-10.

**Next P1 scenarios** (deferred to
later phases):
- ``spread_def_rock_slide``:
  Rock Slide on turn 1, bot's WG
  legal. Rock Slide has
  different target semantics
  (``foeSide`` not ``allAdjacentFoes``).
- ``spread_def_earthquake``:
  Earthquake on turn 1, bot's WG
  legal. Earthquake has grounded
  complications (Levitate / Flying).
- ``redir_followme_basic``:
  Follow Me / Rage Powder on turn 1.

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
- No SCENARIO-10b (Rock Slide) /
  SCENARIO-10c (Earthquake)
  implementation in this phase.
- No Wide Guard scoring added.
- No planner scoring touched.

## 11. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/spread_def_heat_wave.json` | NEW |
| Scripted opp | `bot_vgc2026_scripted_opp.py` | unchanged |
| Runner | `bot_vgc2026_phaseV3a2_reality.py` | unchanged |
| Audit | `doubles_decision_audit_logger.py` | unchanged (gap documented) |
| Opp team | `data/curated_teams/control4a/team_020.json` | Volcarona HW |
| Our team | `data/curated_teams/control4a/team_057.json` | Araquanid WG |
| P0 closeout | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | preconditions |
| P1 probe | `logs/phaseSCENARIO10A_p1_spread_heat_wave_probe_report.md` | gate |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |

## 12. Final Summary

- **Decision**: ``SPREAD_DEF_BASIC_PASS``.
- **Top 5 findings**:
  1. **Heat Wave fires reliably** in
     baseline audit's
     ``scripted_actions`` for both
     battles. Same code path as P0
     setup moves (TR/TW/SD) works
     for spread moves.
  2. **Wide Guard is legal** in bot's
     audit at turns 3, 4, 5 (Araquanid
     in active slot). The
     ``v2l1_legal_action_keys_slotN``
     field captures legality
     correctly.
  3. **Framework gap confirmed**
     (matches SCENARIO-6 expectation):
     bot's audit's
     ``opponent_actions.opponent_used_spread``
     is NOT populated for scripted
     opp moves. Canonical signal =
     baseline audit's
     ``scripted_actions`` (same as P0
     and SCENARIO-10A).
  4. **Lead config works**: Volcarona
     (pos 1) + Blastoise (pos 2) in
     team_020 lead correctly via the
     fixed ``/team`` format. Heat
     Wave + Protect fire as scripted.
  5. **P1 family complete** (basic
     variant): ``spread_def_heat_wave``
     added to scenario library. The
     P1 family has 2 more variants
     deferred: Rock Slide (different
     target semantics) and Earthquake
     (grounded complications).
- **Audit fields sufficient?** YES
  (via baseline audit's
  ``scripted_actions``).
- **Exact next recommended phase**:
  **PAUSE for P1 review** (per
  SCENARIO-6 P1 stop condition:
  after 1 P1 scenario, pause to
  verify before adding Rock Slide
  or Earthquake variants).
- **No scoring change. No commit. No
  ``test_51``. No ``learned_preview_v3d1``.
  No V3d.1 PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
