# Phase SCENARIO-12 — Redirection Basic (Rage Powder)

## 1. Summary

SCENARIO-12 implements the first P1
scenario in the redirection family:
``redir_followme_basic``. The scripted
opp leads with Sinistcha (Rage Powder)
+ Steelix (Protect) and uses Rage
Powder on turn 1. The bot has Heat
Wave as a legal response (an AoE that
hits both opponents, bypassing the
redirection).

**Decision**: ``REDIR_BASIC_PASS``.

Both battles have Rage Powder and
Protect executed in the baseline
audit's ``scripted_actions``. Heat
Wave is legal in the bot's audit at
turns 1, 2, 3 (Volcarona in slot 0).

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

**Naming convention** (per
SCENARIO-6 design): ``redir_<variant>``.
First scenario in the redirection
family (family 8, P1).

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
| 97257 | redir_followme_basic | (1, 0, ragepowder), (1, 1, protect) | V3a2_p00_p2V |
| 97258 | redir_followme_basic | (1, 0, ragepowder), (1, 1, protect) | V3a2_p00_p1V |

Both battles have Rage Powder and
Protect executed.

### 3.2 Treatment audit (bot's perspective)

| battle | Heat Wave legal |
|---|---|
| 97257 | turns 1, 2, 3 (slot 0) |

The bot's Volcarona (Heat Wave) is in
slot 0 (lead), so Heat Wave is legal
from turn 1.

### 3.3 Pass criteria

| criterion | status | evidence |
|---|---|---|
| 2/2 battles ok | ✓ PASS | both baseline audits ok |
| Rage Powder executed | ✓ PASS | baseline scripted_actions |
| scenario_id captured | ✓ PASS | both audits have it |
| Heat Wave legal in some turn | ✓ PASS | turns 1, 2, 3 |
| 0 script failures | ✓ PASS | baseline audits 0 failures |
| no timeout/error | ✓ PASS | runs in 3s |

All 6 criteria pass.

### 3.4 Validator results (with Option C)

```
rage_powder_actually_used: canonical=True xcheck=None gap=True
bot_legal_heat_wave:      passed
no_script_failures:       passed
```

All pass with `bot_opp_action_gap=True`
(expected for scripted scenarios).

## 4. Scenario file

``data/curated_teams/scenarios/redir_followme_basic.json``:

- **scenario_id**:
  ``redir_followme_basic``
- **our_team_file**: team_020
  (Volcarona pos 1 with Heat Wave,
  Blastoise pos 2 with Protect,
  Torterra pos 5 with Wide Guard,
  Hatterene pos 6)
- **opp_team_file**: team_001
  (Sinistcha pos 2 with Rage Powder,
  Steelix pos 4 with Wide Guard /
  Protect, Tyranitar pos 6 with
  Rock Slide)
- **lead**: opp_slot_0=Sinistcha,
  opp_slot_1=Steelix
- **script**: turn_1: opp_slot_0=ragepowder,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: ragepowder, expected: true }``
  - ``expected_bot_legal_response
    { expected: "Heat Wave" }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_001 positions:
1. sneasler
2. **sinistcha** (Rage Powder)
3. talonflame
4. **steelix** (Protect, Wide Guard,
   Heavy Slam, High Horsepower)
5. rotomwash (Levitate)
6. tyranitar (Rock Slide)

team_020 positions:
1. **volcarona** (Heat Wave)
2. blastoise (Protect)
3. meowscarada
4. tinkaton
5. torterra (Wide Guard)
6. hatterene

Lead with Sinistcha (pos 2) +
Steelix (pos 4). Both have Protect.
Sinistcha fires Rage Powder (draws
all opposing attacks to itself).
Steelix Protects.

Bot's Volcarona (Heat Wave) is in
the lead (slot 0); Heat Wave is an
AoE that hits both opponents,
bypassing the Rage Powder redirection
(it still hits Sinistcha, but the
ally also takes damage).

## 6. Why Rage Powder first (not Follow Me)

- Rage Powder has higher priority
  (+4, since it's a powder move).
  Easier to script and verify.
- Follow Me is +0 priority; could
  be outsped by faster opponents
  (e.g., Fake Out from faster mons).
- Rage Powder is the most common
  redirection move in VGC 2026
  (Sinistcha, Amoonguss).

## 7. Anti-leak verification

- ✅ ``ScriptedOpponentPlayer``
  inherits from base ``Player``
  (not bot)
- ✅ Module has no import of
  ``DoublesDamageAwareConfig`` etc.
- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1``
  promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt scoring
- ✅ No planner scoring touched

## 8. Test coverage

- 84 unit tests pass
  (no new tests; the scenario is a
  runtime evidence)
- Reproducible: same scenario file,
  same teams, same result

## 9. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/redir_followme_basic.json` | NEW v1 → v2 |
| Scripted opp | `bot_vgc2026_scripted_opp.py` | unchanged |
| Runner | `bot_vgc2026_phaseV3a2_reality.py` | unchanged |
| Audit | `doubles_decision_audit_logger.py` | unchanged |
| Opp team | `data/curated_teams/item2/team_001.json` | Sinistcha RP |
| Our team | `data/curated_teams/control4a/team_020.json` | Volcarona HW |
| P1 review | `logs/phaseSCENARIO11_p1_review_spread_signal_gap_report.md` | policy |
| Validator | `scenario_probe.py` | Option C |
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |

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
- No SCENARIO-12b (Follow Me
  variant) in this phase.
- No planner scoring touched.

## 11. Final Summary

- **Decision**: ``REDIR_BASIC_PASS``.
- **Top 5 findings**:
  1. **Rage Powder fires reliably** in
     baseline audit's
     ``scripted_actions`` for both
     battles.
  2. **Heat Wave is legal** in bot's
     audit at turns 1, 2, 3 (Volcarona
     in slot 0). Bot has an AoE
     response to bypass redirection.
  3. **Option C validator passes**:
     canonical=True, xcheck=None,
     gap=True (as expected for scripted
     scenarios).
  4. **Lead config works**: Sinistcha
     (pos 2) + Steelix (pos 4) in
     team_001 lead correctly via the
     fixed ``/team`` format. Rage
     Powder + Protect fire as scripted.
  5. **P1 redirection family complete**
     (basic variant):
     ``redir_followme_basic`` added to
     scenario library.
- **Audit fields sufficient?** YES
  (via baseline
  ``scripted_actions``).
- **Exact next recommended phase**:
  **SCENARIO-13 — spread_def_rock_slide**
  (P1, spread variant, different
  target semantics from Heat Wave).
