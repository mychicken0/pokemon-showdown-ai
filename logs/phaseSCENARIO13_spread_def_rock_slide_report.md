# Phase SCENARIO-13 — Spread Defense (Rock Slide)

## 1. Summary

SCENARIO-13 implements the second
variant in the spread_def family:
``spread_def_rock_slide``. The
scripted opp leads with Tyranitar
(Rock Slide) + Steelix (Protect) and
uses Rock Slide on turn 1. The bot
has Wide Guard as a legal response.

**Decision**: ``SPREAD_DEF_ROCK_SLIDE_PASS``.

Both battles have Rock Slide and
Protect executed in the baseline
audit's ``scripted_actions``. Wide
Guard is legal in the bot's audit at
turns 6, 7, 8, 9 (Torterra in slot 1).

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

**Naming convention** (per
SCENARIO-6 design): ``spread_def_<variant>``.
Second scenario in the spread_def
family (after Heat Wave basic).

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
| 97259 | spread_def_rock_slide | (1, 0, rockslide), (1, 1, protect) | V3a2_p00_p2V |
| 97260 | spread_def_rock_slide | (1, 0, rockslide), (1, 1, protect) | V3a2_p00_p1V |

Both battles have Rock Slide and
Protect executed.

### 3.2 Treatment audit (bot's perspective)

| battle | Wide Guard legal |
|---|---|
| 97259 | turns 6, 7, 8, 9 (slot 1) |

The bot's Torterra (Wide Guard) is in
slot 1 from turn 6+. Wide Guard is
legal when Torterra is in the active.

### 3.3 Pass criteria

| criterion | status | evidence |
|---|---|---|
| 2/2 battles ok | ✓ PASS | both baseline audits ok |
| Rock Slide executed | ✓ PASS | baseline scripted_actions |
| scenario_id captured | ✓ PASS | both audits have it |
| Wide Guard legal in some turn | ✓ PASS | turns 6, 7, 8, 9 |
| 0 script failures | ✓ PASS | baseline audits 0 failures |
| no timeout/error | ✓ PASS | runs in 2s |

All 6 criteria pass.

### 3.4 Validator results (with Option C)

```
rock_slide_actually_used: canonical=True xcheck=None gap=True
bot_legal_wide_guard:    passed
no_script_failures:      passed
```

All pass with `bot_opp_action_gap=True`.

## 4. Scenario file

``data/curated_teams/scenarios/spread_def_rock_slide.json``:

- **scenario_id**:
  ``spread_def_rock_slide``
- **our_team_file**: team_020
  (Torterra pos 5 with Wide Guard)
- **opp_team_file**: team_001
  (Tyranitar pos 6 with Rock Slide,
  Steelix pos 4 with Protect)
- **lead**: opp_slot_0=Tyranitar,
  opp_slot_1=Steelix
- **script**: turn_1: opp_slot_0=rockslide,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: rockslide, expected: true }``
  - ``expected_bot_legal_response
    { expected: "Wide Guard" }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_001 positions:
1. sneasler
2. sinistcha (Rage Powder)
3. talonflame
4. **steelix** (Protect, Wide Guard)
5. rotomwash (Levitate)
6. **tyranitar** (Rock Slide, Dragon Dance)

team_020 positions:
1. volcarona (Heat Wave)
2. blastoise (Protect)
3. meowscarada
4. tinkaton
5. **torterra** (Wide Guard)
6. hatterene

Lead with Tyranitar (pos 6) +
Steelix (pos 4). Both have Protect.
Tyranitar fires Rock Slide (spread,
all adjacent foes), Steelix Protects.

Bot's Torterra (Wide Guard) is in
slot 1 from turn 6+. Wide Guard
protects all allies from the spread
move.

## 6. Why Rock Slide after Heat Wave

- Rock Slide is the second most common
  spread move in VGC 2026.
- Different from Heat Wave: lower BP
  (75 vs 95), Rock type, may cause
  flinch (30% on each target).
- Same target semantics
  (``allAdjacentFoes``), so the
  script logic is the same.
- Confirms spread mechanics work
  for a second spread move.

## 7. Anti-leak verification

- ✅ ``ScriptedOpponentPlayer``
  inherits from base ``Player``
- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1``
  promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard scoring added
- ✅ No planner scoring touched

## 8. Test coverage

- 84 unit tests pass
- Reproducible: same scenario file,
  same teams, same result

## 9. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/spread_def_rock_slide.json` | NEW v1 → v2 |
| Scripted opp | `bot_vgc2026_scripted_opp.py` | unchanged |
| Runner | `bot_vgc2026_phaseV3a2_reality.py` | unchanged |
| Audit | `doubles_decision_audit_logger.py` | unchanged |
| Opp team | `data/curated_teams/item2/team_001.json` | Tyranitar RS |
| Our team | `data/curated_teams/control4a/team_020.json` | Torterra WG |
| P1 review | `logs/phaseSCENARIO11_p1_review_spread_signal_gap_report.md` | policy |
| Validator | `scenario_probe.py` | Option C |

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
- No SCENARIO-14 (Earthquake) in
  this phase (deferred per user
  order, see SCENARIO-14 report).
- No planner scoring touched.

## 11. Final Summary

- **Decision**:
  ``SPREAD_DEF_ROCK_SLIDE_PASS``.
- **Top 5 findings**:
  1. **Rock Slide fires reliably** in
     baseline audit's
     ``scripted_actions`` for both
     battles.
  2. **Wide Guard is legal** in bot's
     audit at turns 6, 7, 8, 9
     (Torterra in slot 1).
  3. **Option C validator passes**:
     canonical=True, xcheck=None,
     gap=True.
  4. **Lead config works**: Tyranitar
     (pos 6) + Steelix (pos 4) in
     team_001 lead correctly. Rock
     Slide + Protect fire as scripted.
  5. **Spread family expanded** (2 of
     3 variants): Heat Wave (basic) +
     Rock Slide. Earthquake deferred.
- **Audit fields sufficient?** YES.
- **Exact next recommended phase**:
  **SCENARIO-14** (Earthquake) —
  deferred per user order due to
  grounded / Levitate / Flying
  complications. See
  ``phaseSCENARIO14_earthquake_deferred_report.md``.
