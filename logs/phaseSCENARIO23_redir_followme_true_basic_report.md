# Phase SCENARIO-23 — Follow Me (true variant)

## 1. Summary

SCENARIO-23 implements the followme variant
of the redir family:
``redir_followme_true_basic.json``. The scripted
opp leads with Clefable (Follow Me (true variant)
user) + Arcanine (Protect) and uses
Follow Me (true variant) on turn 1.

**Decision**: ``FOLLOWME_BASIC_PASS``.

Both battles have Follow Me (true variant) and Protect
executed in the baseline audit's
``scripted_actions``. The bot's
Tyranitar (Sand Stream) switches in
later, setting sand that overrides
the terrain/redirect.

**Custom team required**: a custom
opp team
(``followme_demo_v1.json``) was
created in
``data/curated_teams/custom/``
because no curated team has a
Follow Me (true variant) user.

**Default state**: no impact when
``--scenario-file`` is not set.
Backward compatible.

## 2. Verification

- ``git diff --check``: clean
- 84 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change

## 3. Probe results (1 pair = 2 battles)

### 3.1 Baseline audit (scripted opp's perspective)

| battle | scenario_id | executed |
|---|---|---|
| 97280 | redir_followme_true_basic | (1, 0, followme), (1, 1, protect) |
| 97281 | redir_followme_true_basic | (1, 0, followme), (1, 1, protect) |

Both battles have Follow Me (true variant) and
Protect executed.

### 3.2 Pass criteria

| criterion | status |
|---|---|
| 2/2 battles ok | ✓ PASS |
| Follow Me (true variant) executed | ✓ PASS |
| scenario_id captured | ✓ PASS |
| 0 script failures | ✓ PASS |
| no timeout/error | ✓ PASS |

All 5 criteria pass.

### 3.3 Validator (Option C)

```
followme_actually_used: canonical=True gap=True
no_script_failures: passed
```

## 4. Scenario file

``data/curated_teams/scenarios/redir_followme_true_basic.json``:

- **scenario_id**: ``redir_followme_true_basic``
- **our_team_file**:
  ``data/curated_teams/control4a/team_020.json``
- **opp_team_file**:
  ``data/curated_teams/custom/followme_demo_v1.json``
- **lead**: opp_slot_0=Clefable,
  opp_slot_1=Arcanine
- **script**: turn_1: opp_slot_0=followme,
  opp_slot_1=protect
- **validators**:
  - ``expected_scripted_action
    { field: followme, expected: true }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_020 (bot) positions:
1. volcarona
2. blastoise
3. meowscarada
4. tinkaton
5. torterra
6. hatterene

The bot's lead is random. The
canonical signal fires regardless
of the bot's lead (it just verifies
the scripted action fired).

## 6. Custom team

``data/curated_teams/custom/followme_demo_v1.json``
(NEW, 6 mons):

1. **Clefable** (default ability, Leftovers)
   — the Follow Me (true variant) user
2. **Arcanine** (Intimidate, Sitrus
   Berry) — the Protect partner
3. Kingambit (Defiant, Shuca Berry)
4. Garchomp (Rough Skin, Yache Berry)
5. Tyranitar (Sand Stream, Choice Scarf)
6. Volcarona (Flame Body, Lum Berry)

## 7. Why custom team

Per SCENARIO-6 design's P2 readiness
check, no curated team has a
Follow Me (true variant) user. A custom team was
created with the Clefable mon (which
learns Follow Me (true variant) via TM in Gen 9).

## 8. Anti-leak verification

- ✅ No scoring change
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1`` promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt / Encore
  scoring
- ✅ No planner scoring touched

## 9. Library status (post-SCENARIO-23)

- ✅ redir_followme_true_basic (SCENARIO-23, Follow Me (true variant))
- 13 active scenarios total
- 4 custom teams
- 4 deferred scenarios

## 10. Do-Not-Do (Final)

- No scoring change.
- No default flip.
- No ``test_51`` touched.
- No commit / push yet.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1`` promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No audit logger changes.
- No validator code changes.

## 11. References

| source | path | role |
|---|---|---|
| Scenario | ``data/curated_teams/scenarios/redir_followme_true_basic.json`` | NEW v1 → v2 |
| Custom team | ``data/curated_teams/custom/followme_demo_v1.json`` | NEW |
| Opp team | ``data/curated_teams/custom/followme_demo_v1.json`` | Clefable |
| Our team | ``data/curated_teams/control4a/team_020.json`` | bot team |
| Library design | ``logs/phaseSCENARIO6_library_design.md`` | family plan |
| Library closeout | ``logs/phaseSCENARIO20_library_closeout.md`` | preconditions |
| TERRAIN-1 (similar) | ``logs/phaseTERRAIN1_terrain_psychic_basic_report.md`` | audit signal pattern |
