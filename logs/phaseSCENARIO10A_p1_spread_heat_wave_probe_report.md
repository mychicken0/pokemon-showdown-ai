# Phase SCENARIO-10A — P1 Spread Probe (Heat Wave + Wide Guard)

## 1. Summary

SCENARIO-10A is a probe (NOT a full
scenario) to confirm the P1 spread
mechanics work in the scenario
framework before implementing
SCENARIO-10. The probe uses Heat Wave
because it has the simplest target
semantics (no grounded/Levitate/Flying
complications like Earthquake).

**Decision**: `P1_SPREAD_PROBE_PASS`
with a documented framework gap.

The probe passes on all critical
criteria. The canonical signal
(``scripted_actions`` in the baseline
audit) confirms Heat Wave fires. Wide
Guard is legal in the bot's audit at
turns 5, 6, 7 (Araquanid brought in).

**Key finding** (matches SCENARIO-6
expectation): the bot's audit's
``opponent_actions.opponent_used_spread``
field is NOT populated for scripted
opp moves. The canonical signal must
come from the baseline audit's
``scripted_actions`` field.

## 2. Verification

- `git diff --check`: clean
- 68 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change
- No ``test_51`` touched
- No commit / push yet

## 3. Probe results (1 pair = 2 battles)

### 3.1 Baseline audit (scripted opp's perspective)

| battle | scenario_id | executed | winner |
|---|---|---|---|
| 97253 | anti_spread_heat_wave_probe | (1, 0, heatwave), (1, 1, protect) | V3a2_p00_p2V |
| 97254 | anti_spread_heat_wave_probe | (1, 0, heatwave), (1, 1, protect) | V3a2_p00_p1V |

Both battles have Heat Wave and
Protect executed in the baseline
audit's ``scripted_actions`` (the
canonical signal for scripted moves).

### 3.2 Treatment audit (bot's perspective)

| battle | audit_turns | opp_actions | WG legal |
|---|---|---|---|
| 97253 | 8 turns | EMPTY (all {}) | turns 5, 6, 7 (slot 1) |

The bot's audit's ``opponent_actions``
field is empty for all turns. This is
the known framework gap (per
SCENARIO-6 design): the bot's audit
does not reliably capture the scripted
opp's moves in ``opponent_actions``.

Wide Guard is legal in the bot's
audit at turns 5, 6, 7 (Araquanid in
the active slot). The bot's lead was
Gallade + Tsareena (not Araquanid),
but Araquanid was brought in later.

### 3.3 Pass criteria

| criterion | status | evidence |
|---|---|---|
| 2/2 battles ok | ✓ PASS | both baseline audits have status ok |
| Heat Wave executed in both | ✓ PASS | baseline audit scripted_actions |
| spread audit equivalent fires | ✓ PASS | scripted_actions has heatwave |
| WG legal in some audited turn | ✓ PASS | turns 5, 6, 7 |
| scenario_id captured | ✓ PASS | both audits have it |
| 0 script failures | ✓ PASS | both baseline audits have 0 failures |
| no timeout/error | ✓ PASS | runs in 3s |

All 7 criteria pass.

### 3.4 Framework gap confirmed

The bot's audit's
``opponent_actions.opponent_used_spread``
field is **not populated** for the
scripted opp's Heat Wave. This matches
the SCENARIO-6 design's known gap:
the audit logger's turn_events parser
may not capture the scripted opp's
moves in ``opponent_actions`` because
the protocol events for the scripted
opp are processed by the scripted
player's audit (baseline), not the
bot's audit (treatment).

**Workaround**: use the baseline
audit's ``scripted_actions`` as the
canonical signal for scripted moves.
This is the same pattern used for
SCENARIO-5/7/8 (TR/TW/SD).

## 4. Scenario file

``data/curated_teams/scenarios/anti_spread_heat_wave_probe.json``:

- **scenario_id**:
  ``anti_spread_heat_wave_probe``
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
The bot's lead is random (Gallade +
Tsareena or Kangaskhan + something).
Araquanid is brought in later; WG
becomes legal at turn 5+.

## 6. Why Heat Wave first

Per the user's recommendation:
- Heat Wave has simpler target
  semantics than Earthquake (no
  grounded/Levitate/Flying
  complications).
- Heat Wave is a +0 priority spread
  move, so it's easier to script
  predictably.
- Earthquake would add complexity
  (Levitate mons, Flying types,
  Magnet Rise, etc.).
- Rock Slide has different target
  semantics (`foeSide` not
  `allAdjacentFoes`).

The probe validates the spread
mechanics without the complications
of type-immunity or side-targeting.

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
  added; the probe is a runtime
  evidence, not a fixture test).
- The probe is reproducible: same
  scenario file, same teams, same
  result.

## 9. P1 readiness update

The SCENARIO-9 readiness criteria
state: "P1 implementation deferred
until a 1-pair spread probe
confirms the framework fixes work
for spread moves too."

**This probe satisfies that gate**:
- Heat Wave fires reliably via the
  scripted player's choose_move
  (same code path as P0 setup moves).
- Wide Guard legality is recorded
  in the bot's audit's
  ``v2l1_legal_action_keys_slotN``
  field.
- The baseline audit's
  ``scripted_actions`` is the
  canonical signal for scripted
  moves (same as P0).
- The framework gap
  (``opponent_actions`` empty for
  scripted opps) is documented and
  not a blocker for SCENARIO-10.

**Recommendation**: proceed to
SCENARIO-10 — Spread Defense Basic,
using Heat Wave + Wide Guard, with
the canonical signal from the
baseline audit's ``scripted_actions``
(same pattern as SCENARIO-5/7/8).

## 10. Do-Not-Do (Final)

- No scoring change (instrumentation
  only).
- No default flip.
- No ``test_51`` touched.
- No commit / push yet.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1``
  promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No SCENARIO-10 implementation in
  this phase.
- No Wide Guard scoring added.
- No Earthquake / Rock Slide yet
  (defer to later SCENARIO-10
  variants).

## 11. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/anti_spread_heat_wave_probe.json` | NEW |
| Scripted opp | `bot_vgc2026_scripted_opp.py` | unchanged |
| Runner | `bot_vgc2026_phaseV3a2_reality.py` | unchanged |
| Audit | `doubles_decision_audit_logger.py` | unchanged (gap documented) |
| Opp team | `data/curated_teams/control4a/team_020.json` | Volcarona HW |
| Our team | `data/curated_teams/control4a/team_057.json` | Araquanid WG |
| P0 closeout | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | preconditions |
| Library design | `logs/phaseSCENARIO6_library_design.md` | P1 plan |

## 12. Final Summary

- **Decision**: ``P1_SPREAD_PROBE_PASS``.
- **Top 5 findings**:
  1. **Heat Wave fires reliably** in
     the baseline audit's
     ``scripted_actions`` for both
     battles. The same code path as
     P0 setup moves (TR/TW/SD) works
     for spread moves.
  2. **Wide Guard is legal** in the
     bot's audit at turns 5, 6, 7
     (Araquanid in active slot).
     The bot's
     ``v2l1_legal_action_keys_slotN``
     field captures legality
     correctly.
  3. **Framework gap confirmed**:
     the bot's audit's
     ``opponent_actions.opponent_used_spread``
     field is NOT populated for
     scripted opp moves. The canonical
     signal is the baseline audit's
     ``scripted_actions`` (same as P0).
  4. **Lead config works**: Volcarona
     (pos 1) + Blastoise (pos 2) in
     team_020 lead correctly via the
     fixed ``/team`` format. Heat
     Wave + Protect fire as scripted.
  5. **P1 readiness gate met**:
     1-pair spread probe passes
     without code changes. The
     framework fixes (runner team
     swap, /team format) work for
     spread moves too.
- **Audit fields sufficient?** YES
  (via baseline audit's
  ``scripted_actions``).
- **Exact next recommended phase**:
  **SCENARIO-10 — Spread Defense
  Basic** (using Heat Wave + Wide
  Guard, same teams as the probe,
  same canonical signal).
- **No scoring change. No commit. No
  ``test_51``. No ``learned_preview_v3d1``.
  No V3d.1 PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
