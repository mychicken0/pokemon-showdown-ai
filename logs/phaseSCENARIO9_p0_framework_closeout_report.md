# Phase SCENARIO-9 — P0 Framework Closeout

## 1. Summary

**Decision**: `P0_FRAMEWORK_READY`.

SCENARIO-9 is a docs/audit-only phase.
It reviews the 3 P0 scenarios
(anti_tr_basic, anti_tw_basic,
anti_stat_boost_basic), summarizes the
framework-level bugs found and fixed,
confirms the tests that pin those fixes,
and defines P1 readiness criteria.

**No new code, no new scenario, no
battle run, no commit/push until
user approval**.

## 2. P0 trio — final evidence

Each scenario re-verified with the
final code (post-`/team` format fix,
post-runner team swap fix).

### 2.1 anti_tr_basic (SCENARIO-5)

| battle | scenario_id | winner | executed | failures |
|---|---|---|---|---|
| 97245 | anti_tr_basic | V3a2_p00_p2V | (1, 0, trickroom), (1, 1, protect) | 0 |
| 97246 | anti_tr_basic | V3a2_p00_p1V | (1, 0, trickroom), (1, 1, protect) | 0 |

- Lead: Hatterene + Blastoise
- Script: TR (Hatterene) + Protect (Blastoise)
- Bot response: Zoroark-H Taunt, Whimsicott Encore

### 2.2 anti_tw_basic (SCENARIO-7)

| battle | scenario_id | winner | executed | failures |
|---|---|---|---|---|
| 97247 | anti_tw_basic | V3a2_p00_p2V | (1, 0, tailwind), (1, 1, protect) | 0 |
| 97248 | anti_tw_basic | V3a2_p00_p1V | (1, 0, tailwind), (1, 1, protect) | 0 |

- Lead: Whimsicott + Kingambit
- Script: Tailwind (Whimsicott) + Protect (Kingambit)
- Bot response: Zoroark-H Taunt

### 2.3 anti_stat_boost_basic (SCENARIO-8)

| battle | scenario_id | winner | executed | failures |
|---|---|---|---|---|
| 97249 | anti_stat_boost_basic | V3a2_p00_p2V | (1, 0, swordsdance), (1, 1, protect) | 0 |
| 97250 | anti_stat_boost_basic | V3a2_p00_p1V | (1, 0, swordsdance), (1, 1, protect) | 0 |

- Lead: Kingambit + Incineroar
- Script: Swords Dance (Kingambit) + Protect (Incineroar)
- Bot response: Zoroark-H Taunt

### 2.4 P0 summary

- 3/3 P0 families pass
- 6/6 battles ok
- 6/6 scripted actions fired (TR / TW / SD in slot 0, Protect in slot 1)
- 6/6 scenario_ids captured
- 0 meaningful script failures
- 0 audit-signal false negatives

## 3. Framework-level bugs found and fixed

### 3.1 Bug A: Runner team swap (SCENARIO-8)

**File**: `bot_vgc2026_phaseV3a2_reality.py`

**Before**:
```python
team=opp_team_str if side == "p1" else our_team_str,
```

**After**:
```python
team=opp_team_str,
```

**Symptom**: When the script's
`opp_team_file` (e.g., team_006 with
Kingambit) and `our_team_file` (e.g.,
team_027 without Kingambit) did not
overlap, the `side="p2"` battle
couldn't find the lead species in
its team, fell back to random
teampreview, and the script's
slot 0 stat boost failed with
`move_not_available` (no Kingambit
in the lead).

**Why it was masked in SCENARIO-5/7**:
Both teams had the lead species in
common. team_020 (Hatterene) and
team_027 (Hatterene); team_046
(Whimsicott) and team_027 (Whimsicott).
The team swap accidentally picked the
correct species for slot 0.

**Why the new code is correct**:
The scripted player IS the "opp" in
the scenario file. Its team is always
the scenario's `opp_team_file`. The
`side` flag controls whether the bot
is p1 or p2, NOT which team the
scripted player gets.

### 3.2 Bug B: /team format (SCENARIO-8)

**File**: `bot_vgc2026_scripted_opp.py`

**Before**:
```python
chosen = [
    lead_positions[0],  # digit 1 = lead 0
    back_positions[0],  # digit 2 = back 0 (NOT lead!)
    lead_positions[1],  # digit 3 = lead 1 (NOT back!)
    back_positions[1],  # digit 4 = back 1
]
```

**After**:
```python
chosen = [
    lead_positions[0],  # digit 1 = lead 0
    lead_positions[1],  # digit 2 = lead 1
    back_positions[0],  # digit 3 = back 0
    back_positions[1],  # digit 4 = back 1
]
```

**Symptom**: With the old format,
showdown interpreted the /team
string as the leads being digits
1 and 2 (i.e., `lead_positions[0]`
and `back_positions[0]`). The
script's `slot 1` (which referenced
`lead_positions[1]`) was actually
placed in slot 2 (a back position).
The script's slot 1 Protect
referenced a back mon that might
not have Protect.

**Why it was masked in SCENARIO-5/7**:
The accidental lead 1 was a random
back mon. If that mon had Protect
(common in VGC), the script's
slot 1 Protect fired on the wrong
mon but still succeeded. The test
passed for the wrong reason.

**Confirmed empirically** (TT7 test):
sending `/team 1234` to a doubles
battle resulted in leads = positions
1, 2 (Volcarona + Blastoise), NOT
positions 1, 3.

**Confirmed via poke-env docs**:
"'3461' indicates leading with
pokemon 3, with pokemons 4, 6 and 1
in the back in single battles or
leading with pokemons 3 and 4 with
pokemons 6 and 1 in the back in
double battles." — the leads are
the FIRST 2 digits of the /team
string.

### 3.3 Bug C: SCENARIO-5 v23 stale lead
(fixed during SCENARIO-8)

**File**:
`data/curated_teams/scenarios/anti_tr_basic.json`

**Before** (v4):
```json
"lead": {
  "opp_slot_0": "Hatterene",
  "opp_slot_1": "Volcarona"
}
```

**After** (v5):
```json
"lead": {
  "opp_slot_0": "Hatterene",
  "opp_slot_1": "Blastoise"
}
```

**Why**: With the /team format bug
fixed, the original Hatterene +
Blastoise lead works correctly.
The v4 Volcarona lead was a
workaround for the broken format
(now unnecessary).

### 3.4 OTS / teampreview handling
(unchanged from SCENARIO-4)

The scripted player still:
- sends `/rejectopenteamsheets` to
  skip the OTS handshake
- sets `self._accept_open_team_sheet = False`
- uses the lead config from the
  scenario JSON (not the bot's own
  lead preference)

This continues to work in P0 trio.

## 4. Tests covering framework bugs

### 4.1 Existing tests (still pass)

| test | what it covers | result |
|---|---|---|
| `test_lead_with_tr_setter` | Hatterene in lead for SCENARIO-5 | OK |
| `test_fallback_to_random_when_no_match` | No Hatterene → random | OK |
| `test_record_success` | success recording | OK |
| `test_record_failure` | failure recording | OK |
| `test_no_audit_data_with_no_script_failures` | validator | OK |
| ... (62 more) | (unchanged) | OK |

### 4.2 New test added in SCENARIO-9

| test | what it pins | result |
|---|---|---|
| `test_lead_with_stat_boost_setter` | Kingambit + Incineroar are the EXACT 2 leads for SCENARIO-8 | OK |

**Verified to catch the bug**:
temporarily reverting the /team
format fix to the old
`[lead, back, lead, back]` order
causes this test to FAIL with:

```
- ['Kingambit', 'Kommoo']
+ ['Incineroar', 'Kingambit'] : lead_species=['Kingambit', 'Kommoo'] (positions=[4, 6, 3, 5])
```

The bug is the test failing on the
lead species. The test would also
catch Bug A (runner team swap) if
extended to test the runner.

### 4.3 Test count

- Before SCENARIO-9: 67 unit tests pass
- After SCENARIO-9: 68 unit tests pass
  (added 1 test)

### 4.4 Test coverage gaps

- **Runner team swap (Bug A)** is
  tested only by integration (the
  SCENARIO-8 1-pair probe). A unit
  test for the runner would require
  mocking poke-env's Player class.
  The integration test is
  sufficient for now.
- **OTS / teampreview** is exercised
  by all 3 P0 scenarios (all
  successfully skip OTS via
  `/rejectopenteamsheets`).
- **Showdown doubles /team format**
  is now pinned by
  `test_lead_with_stat_boost_setter`.

## 5. P1 readiness criteria

The 5 P0 framework gates:

| # | gate | status |
|---|---|---|
| 1 | 3/3 P0 scenarios pass with final code | PASS |
| 2 | 0 meaningful script failures in P0 | PASS |
| 3 | Lead config honored exactly for non-overlapping teams | PASS (post-Bug A fix) |
| 4 | /team format pinned by a unit test | PASS (test_lead_with_stat_boost_setter) |
| 5 | 67+ unit tests pass | PASS (68 pass) |

All 5 gates met.

### 5.1 P1 family: spread_def
(SCENARIO-10 candidate)

**Family**: opp uses Heat Wave / Rock
Slide / Earthquake; bot has Wide
Guard legal.

**Complexity vs P0**:
- P0: setup moves with self-target
  or no target. Script just selects
  the move.
- P1 (spread): moves have
  multi-target semantics. Wide
  Guard protects all allies; the
  script needs to know which target
  the move hits (Heat Wave hits
  all adjacent foes; Earthquake
  hits all non-flying adjacent).

**Framework implications**:
- The script's `_build_move_order`
  needs to handle target selection
  for spread moves.
- The audit logger needs to track
  `opponent_used_spread` (already
  exists per SCENARIO-6 design).
- The bot's audit needs to record
  Wide Guard legality
  (`expected_bot_legal_response`
  validator already exists).

**Readiness**:
- Validator types existing: YES
  (4 types cover the spread case).
- Audit fields existing: YES
  (`opponent_used_spread`).
- Spread move ID normalization
  for Heat Wave / Rock Slide /
  Earthquake: needs verification.
- Wide Guard legality check on
  bot side: needs a target that
  spread move would hit.

### 5.2 P1 family: redir
(SCENARIO-11+ candidate)

**Family**: opp uses Follow Me /
Rage Powder; bot has AoE move or
single-target redirect counter.

**Complexity vs P1**:
- Redir moves target the user
  (self-target). The script's
  `_build_move_order` needs to
  select self as target.
- Audit fields: `opponent_used_followme`,
  `opponent_used_ragepowder` (both
  exist per SCENARIO-6 design).

**Readiness**:
- Similar to spread: target
  selection needs care.

### 5.3 Risks for P1

| risk | mitigation |
|---|---|
| Spread move ID normalization (heatwave / heat-wave / heat wave) | Already handled by `_normalize_move_id` per SCENARIO-3 |
| Script's slot for spread move (single slot, but moves hit multiple) | The audit's `opponent_used_spread` is set on ANY turn the opp uses a spread move; no slot logic needed |
| Bot's Wide Guard needs a target | Use `expected_bot_legal_response` validator with move "Wide Guard"; if bot has WG in moveset, it's legal |
| Target field for Heat Wave vs Earthquake | Heat Wave is `allAdjacentFoes`; Earthquake is `allAdjacent`. Different target types. Audit may not capture correctly. |
| Wide Guard use tracking | The bot's audit has `opponent_used_spread`. Need to verify WG usage is recorded. |

### 5.4 P1 recommendation

Defer P1 implementation until:
1. 5 framework gates above remain
   green.
2. A spread probe (1-pair) is run
   for SCENARIO-10 with a
   non-overlapping-team setup
   (similar to SCENARIO-8) to
   confirm the runner team swap
   fix and /team format fix work
   for spread moves too.
3. A unit test for target
   selection in
   `_build_move_order` is added.

## 6. Stable state

- 0 scoring change
- 0 default flips
- 0 commit / push yet for SCENARIO-9
- 0 model artifacts
- 0 ``test_51`` touched
- 0 RL / V3d.1

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
- No SCENARIO-10+ implementation
  in this phase.
- No runner code change beyond
  the SCENARIO-8 fix already
  pushed.

## 8. References

| source | path | role |
|---|---|---|
| Runner fix | `bot_vgc2026_phaseV3a2_reality.py` | Bug A |
| /team fix | `bot_vgc2026_scripted_opp.py` | Bug B |
| Lead test | `test_bot_vgc2026_scripted_opp.py` | new + updated tests |
| Scenario files | `data/curated_teams/scenarios/anti_*.json` | 3 P0 scenarios |
| Design | `logs/phaseSCENARIO6_library_design.md` | P0/P1/P2 plan |
| SCENARIO-5 report | `logs/phaseSCENARIO5_v22_report.md` | initial pipeline |
| SCENARIO-7 report | `logs/phaseSCENARIO7_anti_tw_basic_report.md` | family 2 |
| SCENARIO-8 report | `logs/phaseSCENARIO8_anti_stat_boost_basic_report.md` | family 3 + bugs |
| SCENARIO-9 (this) | `logs/phaseSCENARIO9_p0_framework_closeout_report.md` | closeout |

## 9. Final Summary

- **Decision**: `P0_FRAMEWORK_READY`.
- **Top 5 findings**:
  1. **3/3 P0 families pass** with
     final code: anti_tr_basic,
     anti_tw_basic, anti_stat_boost_basic.
  2. **6/6 battles ok** (2 per family).
  3. **2 framework bugs found and
     fixed**: runner team swap
     (Bug A), /team format
     (Bug B). Both surfaces when
     scenario uses non-overlapping
     teams.
  4. **1 new test added** that pins
     the /team format fix:
     `test_lead_with_stat_boost_setter`.
     Verified to catch the bug
     (FAIL with old format, OK with
     new format).
  5. **P1 readiness criteria defined**:
     5 framework gates all green;
     spread_def and redir families
     have existing audit fields
     and validator types; defer P1
     implementation until a 1-pair
     spread probe confirms the
     framework fixes work for spread
     moves too.
- **Audit fields sufficient?** YES.
- **Exact next recommended phase**:
  **SCENARIO-10 — Spread Defense
  Basic (P1 candidate)** pending
  user approval. Stop after SCENARIO-10
  for P1 review (per SCENARIO-6
  P1 stop condition).
- **No scoring change. No default
  flip. No ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption. No commit/push
  until user approval.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
