# Phase TERRAIN-2A — Psychic Terrain Cleanup

## 1. Summary

TERRAIN-2A fixes the
**lead/species mismatch** in the
Psychic Terrain scenario.

**Before** (v2, audit signal only):
- `lead.opp_slot_0`: "Indeedee"
- `validators`: `expected_audit_signal`
- Issue: Indeedee is from Legends
  Arceus, not in Paldea Champions
  format. The showdown team
  validator rejects it. The actual
  setter in the team is Espathra.
- The canonical signal approach
  (`expected_scripted_action`) was
  not used because the script's
  Psychic Terrain was failing with
  "move_not_available" (the script
  was looking for the move on
  Indeedee, not on the actual active
  Espathra).

**After** (v3, canonical signal works):
- `lead.opp_slot_0`: "Espathra"
  (matches the actual team setter)
- `validators`:
  `expected_scripted_action`
  (canonical signal)
- Result: canonical=True, gap=True,
  passed

**Decision**: `CLEANUP_DONE` — the
scenario now uses the canonical
signal approach like Electric and
Grassy Terrain variants. The
description documents the cleanup.

## 2. Root cause analysis

The issue was a **lead/species
mismatch**: the lead config said
"Indeedee" but the showdown
teampreview put Espathra in the
lead (because the showdown teampreview
is automated and the bot picks the
lead based on the actual team, not
the lead config).

When the script's `choose_move`
was called for slot 0, it was
looking for the Psychic Terrain
move on Indeedee (not in the
active). The showdown's protocol
showed Espathra's moves (including
Psychic Terrain) but the script
checked the lead config's species
(Indeedee), not the actual active
mon (Espathra).

The fix: update the lead config to
match the actual team setter
(Espathra). Now the script's
`choose_move` looks for the move
on the right mon, and the canonical
signal fires.

## 3. Verification

- `git diff --check`: clean
- 84 unit tests pass
- 1-pair probe: 2/2 battles ok
- No scoring / default change
- Lead/species match: yes (both say
  Espathra)

## 4. Probe results (1 pair = 2 battles)

### 4.1 Baseline audit (scripted opp's perspective)

Both battles have Psychic Terrain
and Protect executed in the
baseline audit's `scripted_actions`.

### 4.2 Validator (Option C)

```
psychic_terrain_actually_used: canonical=True gap=True
no_script_failures: passed
```

All pass with `bot_opp_action_gap=True`
(expected for scripted scenarios).

## 5. Lesson learned

The lead config MUST match the
actual team setter for the canonical
signal approach to work. The
`expected_audit_signal` approach
is a workaround for the mismatch
but is not "clean" — the canonical
signal is the proper validator.

## 6. Files changed

- `data/curated_teams/scenarios/terrain_psychic_basic.json`:
  - `lead.opp_slot_0`: "Indeedee" →
    "Espathra"
  - `validators[0].type`:
    "expected_audit_signal" →
    "expected_scripted_action"
  - `validators[0].name`:
    "psychic_terrain_set" →
    "psychic_terrain_actually_used"
  - `validators[0].field`: "fields" →
    "psychicterrain"
  - `description`: added "PARTIAL"
    marker (now removed since it's
    clean)
  - `version`: 2 → 3

## 7. Post-cleanup state

All 3 terrain variants now use the
same pattern (`expected_scripted_action`
with `canonical=True`):

| terrain | validator | status |
|---|---|---|
| Psychic | `expected_scripted_action` | PASS (clean) |
| Electric | `expected_scripted_action` | PASS (clean) |
| Grassy | `expected_scripted_action` | PASS (clean) |

The `expected_audit_signal` approach
is no longer used for any active
scenario in the library.

## 8. References

| source | path | role |
|---|---|---|
| Scenario | `data/curated_teams/scenarios/terrain_psychic_basic.json` | v2 → v3 |
| Custom team | `data/curated_teams/custom/terrain_demo_v1.json` | unchanged (Espathra already) |
| TERRAIN-1 (v2 issue) | `logs/phaseTERRAIN1_terrain_psychic_basic_report.md` | original |
| Library closeout | `logs/phaseSCENARIO20_library_closeout.md` | preconditions |
