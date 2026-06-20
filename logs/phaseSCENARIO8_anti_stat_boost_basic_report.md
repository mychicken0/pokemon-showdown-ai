# Phase SCENARIO-8 — Anti-Stat-Boost Response Probe

## 1. Summary

SCENARIO-8 implements the third family
in the P0 trio: Anti-Stat-Boost.
The scripted opp leads with Kingambit +
Incineroar, sets Swords Dance on turn 1,
and uses Protect on the partner. The
bot's Zoroark-H has Taunt as a legal
response.

**Decision**: `FAMILY3_PASS`. SD fires
in both battles via the scripted opp's
perspective. Swords Dance is the most
common physical setup move in VGC;
this scenario validates the bot's
ability to handle physical setup with
existing Taunt/Encore legal moves.

**Side effects fixed during this phase**:

1. **Runner team assignment** (runner):
   the scripted player always uses the
   scenario's `opp_team_file`, NOT a
   swap based on `side`. This was a
   pre-existing bug that surfaced when
   SCENARIO-8's two teams had no species
   overlap.

2. **`/team` format** (scripted player):
   the showdown doubles /team format is
   `lead, lead, back, back` (leads at
   positions 1 and 2 of the 4-digit
   string), NOT `lead, back, lead, back`
   as the previous code assumed. The
   previous bug was masked when the
   random back mon also had Protect.

3. **SCENARIO-5 lead** (scenario file):
   restored to Hatterene + Blastoise
   (the original). Bumped to version 5.

## 2. Verification

- `git diff --check`: clean
- 67 unit tests pass (lead test updated
  to use new /team format)
- 1-pair probe: 2/2 battles ok
- No scoring / default change
- No ``test_51`` touched
- No commit / push yet

## 3. Probe results (1 pair = 2 battles)

| battle | scenario_id | scripted_actions executed | failures |
|---|---|---|---|
| 97241 | anti_stat_boost_basic | (1, 0, swordsdance), (1, 1, protect) | 0 |
| 97242 | anti_stat_boost_basic | (1, 0, swordsdance), (1, 1, protect) | 0 |

Both battles have Swords Dance and
Protect executed in the baseline audit
(scripted opp's perspective).

## 4. Scenario file

``data/curated_teams/scenarios/anti_stat_boost_basic.json``:

- **scenario_id**: ``anti_stat_boost_basic``
- **our_team_file**: team_027 (Zoroark-H
  has Taunt at pos 5; Hatterene at pos 6
  has Dazzling Gleam, but NO Haze)
- **opp_team_file**: team_006 (Kingambit
  has Swords Dance + Protect at pos 4;
  Incineroar has Fake Out + Protect at
  pos 3)
- **lead**: opp_slot_0=Kingambit,
  opp_slot_1=Incineroar
- **script**: turn_1: opp_slot_0=swordsdance,
  opp_slot_1=protect
- **validators**:
  - ``expected_opp_action_used { field:
    stat_boost_setup, expected: true }``
  - ``expected_bot_legal_response
    { expected: Taunt }``
  - ``no_script_failures``

## 5. Lead config reasoning

team_006 positions:
1. gengar
2. floetteeternal
3. **incineroar** (Fake Out + Protect)
4. **kingambit** (SD + Protect)
5. sneasler (Fake Out + Protect)
6. kommoo (Clangorous Soul + Protect)

team_027 positions:
1. chandelure
2. sneasler
3. basculegion
4. whimsicott
5. **zoroarkhisui** (Taunt + Icy Wind)
6. hatterene (Psychic + Dazzling Gleam)

Lead with Kingambit (pos 4) + Incineroar
(pos 3). Both have Protect. Zoroark-H
in bot team can Taunt Kingambit's SD
(Zoroark-H has 143 base speed; Kingambit
at 50 is much slower, so Zoroark-H's
Taunt goes first).

## 6. Side effects: runner team swap fix

Original runner code:
```python
team=opp_team_str if side == "p1" else our_team_str,
```

This worked for SCENARIO-5/7 because
both teams had overlapping species
(e.g., Hatterene in both team_020 and
team_027). For SCENARIO-8, team_006
(Kingambit) and team_027 (no Kingambit)
do not overlap, so the side="p2" battle
couldn't find Kingambit in the team and
fell back to random teampreview.

**Fix**: scripted player always uses
`opp_team_str` (its own team from the
scenario file). The `side` flag controls
bot position, not scripted team.

This is the correct semantic: the
scripted player IS the "opp" in the
scenario file, so it always uses
`opp_team_file`.

## 7. Side effects: /team format fix

Original code built:
```python
chosen = [
    lead_positions[0],  # digit 1
    back_positions[0],  # digit 2
    lead_positions[1],  # digit 3
    back_positions[1],  # digit 4
]
```

This assumed the showdown doubles
/team format was `[lead, back, lead,
back]` (leads at positions 1, 3 of the
4-digit string).

**Empirical test** (TT7): sending
/team 1234 to a doubles battle results
in leads = positions 1, 2 (Volcarona
+ Blastoise), not 1, 3.

**Confirmed via poke-env docs**:
"'3461' indicates leading with pokemon
3, with pokemons 4, 6 and 1 in the
back in single battles or leading with
pokemons 3 and 4 with pokemons 6 and 1
in the back in double battles." — the
leads are the FIRST 2 digits.

**Fix**:
```python
chosen = [
    lead_positions[0],  # digit 1 = lead 0
    lead_positions[1],  # digit 2 = lead 1
    back_positions[0],  # digit 3 = back 0
    back_positions[1],  # digit 4 = back 1
]
```

The previous code was masked when the
random back mon also had Protect (e.g.,
Sneasler at pos 5 in team_006 has
Protect, so the script's "slot 1
Protect" would still fire on Sneasler
even though the lead config said
Incineroar).

For SCENARIO-5 v23 with Hatterene +
Volcarona lead, the back[0] was
Tinkaton (pos 4 in team_020), which has
NO Protect. The script's slot 1 Protect
failed with `move_not_available`. The
fix to /team format makes Volcarona the
actual lead 1, so Protect fires.

## 8. Anti-leak verification

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

## 9. Test coverage

- **Lead test updated**:
  ``test_lead_with_tr_setter`` now uses
  ``[positions[0], positions[1]]`` to
  match the new /team format.
- All 67 unit tests pass.
- 6+ probe battles across SCENARIO-5,
  SCENARIO-7, SCENARIO-8 all pass.

## 10. Stable state

- 0 scoring change
- 0 default flips
- 0 commit / push yet
- 0 model artifacts
- 0 ``test_51`` touched
- 0 RL / V3d.1

## 11. Do-Not-Do (Final)

- No scoring change (instrumentation
  only).
- No default flip.
- No ``test_51`` touched.
- No commit / push yet.
- No 5-pair / 20-pair.
- No ``learned_preview_v3d1`` promotion.
- No V3d.1 PAUSE resumption.
- No ``logs/vgc2026_phaseV3d1_model.json``.
- No SCENARIO-9+ implementation in
  this phase.

## 12. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/anti_stat_boost_basic.json` | NEW |
| Scripted opp | `bot_vgc2026_scripted_opp.py` | /team format fix |
| Runner | `bot_vgc2026_phaseV3a2_reality.py` | team swap fix |
| Audit | `doubles_decision_audit_logger.py` | unchanged |
| Opp team | `data/curated_teams/control4a/team_006.json` | Kingambit SD |
| Our team | `data/curated_teams/control4a/team_027.json` | Zoroark-H Taunt |
| Design | `logs/phaseSCENARIO6_library_design.md` | preconditions |
| Sibling 1 | `data/curated_teams/scenarios/anti_tr_basic.json` | v5 (lead restored) |
| Sibling 2 | `data/curated_teams/scenarios/anti_tw_basic.json` | unchanged |

## 13. Final Summary

- **Decision**: ``FAMILY3_PASS``.
- **Top 5 findings**:
  1. **SD fires in both battles**:
     scripted_actions contains
     ``(1, 0, 'swordsdance')`` with
     ``executed: True`` for both
     battles. Validates the basic
     stat-boost anti-script path.
  2. **Runner team swap bug fixed**:
     scripted player always uses
     ``opp_team_file`` (its own team).
     The side flag controls bot
     position only. Critical for any
     non-overlapping-team scenario.
  3. **/team format bug fixed**:
     showdown doubles /team format is
     ``lead, lead, back, back`` (leads
     at positions 1, 2 of the 4-digit
     string), confirmed empirically
     via TT7 test. The previous
     ``lead, back, lead, back``
     interpretation was masked by
     random back mons often having
     Protect.
  4. **SCENARIO-5 lead restored** to
     Hatterene + Blastoise (the
     original, now works correctly
     with the fixed /team format).
     Bumped to version 5.
  5. **All 3 P0 scenarios pass**:
     SCENARIO-5 (anti_tr_basic),
     SCENARIO-7 (anti_tw_basic),
     SCENARIO-8 (anti_stat_boost_basic).
     67 unit tests pass; lead test
     updated to match new format.
- **Audit fields sufficient?** YES.
- **Exact next recommended phase**:
  **PAUSE for review** per SCENARIO-6
  stop condition (after 3 P0 scenarios,
  pause to fix framework before P1).
- **No scoring change. No commit. No
  ``test_51``. No ``learned_preview_v3d1``.
  No V3d.1 PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact when
  --scenario-file is not set).
