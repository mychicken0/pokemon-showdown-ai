# Phase 6.4.0 — Handoff / State Sync

**Date**: 2026-06-22
**Status**: `DOCS_SYNCED`
**Phase**: 6.4.0 (handoff / state sync, docs-only)

## Summary

Phase 6.4.0 is a docs-only handoff phase. It updates the project's
handoff surface (`CURRENT_STATE.md`, `walkthrough.md`) to reflect the
most recent closed work and current next-step status. No code
changes, no test changes, no scoring changes, no default flips.

## Docs changed

- `CURRENT_STATE.md`:
  - "Last updated" header bumped to 2026-06-22.
  - "Current Decisions → Random Doubles" expanded with Phase 6.3.8a
    status (broad + narrow) and the WT-2 closure.
  - "Recommended Next Step" expanded with the Anti-TR / V3a.3 / WT-3
    / scenario / Phase 7 notes from AGENTS.md.
  - "Working Tree" updated with the 4 most recent pushed commits.
  - "Do Not Do" expanded with Anti-TR / V3a / Phase 7 / RL constraints.
  - Appended phase sections for WT-2, 6.3.8a, 6.3.9, and 6.4.0.

- `walkthrough.md`:
  - Appended 4 short phase closeout entries at the end:
    - WT-2 setter audit closeout
    - Phase 6.3.8a narrow flag integration
    - Phase 6.3.9 paired-test path hygiene
    - Phase 6.4.0 handoff / state sync (this phase)

- `README.md`:
  - Reviewed. No stale "current status" / "latest phase" / test-status
    claims were found, so no edit was made.

## Statuses synced

- **WT-2** setter audit: CLOSED as `SWITCH_SCORING_GAP_CONFIRMED`.
  No scoring change. No default flip. WT-3/4 remain future work.
- **Phase 6.3.8a** narrow flag: WIRED into scoring. Default remains
  `False`. Opt-in only. 323 targeted tests passed.
- **Phase 6.3.8** broad flag: still BLOCKED (paired gates failed).
  Default remains `False`. Opt-in only.
- **Phase 6.3.9** paired-test path hygiene: CLOSED. 93/93 in paired
  tests, 337/337 in targeted suite.
- **Phase 6.4.0** handoff sync: this phase.
- **PLANNER-ANTI-TR**: opt-in only, documented -6pp regression at
  unknown Magic Bounce target, no default flip, no species-based
  Magic Bounce deduction.
- **Learned preview V3***: opt-in only, V3a.3 side-collapsed, do
  not adopt as default.
- **RL training (Phase 7)**: not approved per RL-8 closeout, do not
  start without explicit authorization.

## Constraints respected

- ✅ No code changes
- ✅ No test changes
- ✅ No scoring changes
- ✅ No default flips
- ✅ No benchmarks run
- ✅ No official Pokémon Showdown servers
- ✅ No commit (per task)
- ✅ No push (per task)
- ✅ test_51 untouched
- ✅ Anti-Trick-Room logic untouched
- ✅ Weather/Terrain behavior untouched
- ✅ Production scoring untouched

## Recommended next phase candidates

None of these are auto-started. All are gated by user authorization.

1. **V3a.3 rerun (VGC preview)**
   - 100-pair paired qualification, `learned_preview_v3a1` vs
     `matchup_top4_v3`.
   - Localhost only. Predeclare all gates before running.
   - The previous V3a.3 was BLOCKED on side-collapse 0.14 > 0.10.
     A rerun needs a clear fix for the side-collapse before it is
     started.

2. **WT-3 (type-boost scoring calibration)**
   - Update scoring so Hurricane in rain, Psychic in Psychic Terrain,
     etc. receive a measurable boost.
   - Requires a new evidence chain (fixture test → smoke → paired).
   - Must not weaken any existing adopted safety.

3. **SCENARIO-ROADMAP successor**
   - A new scenario-targeting phase to add to the SCENARIO library
     (e.g. SCENARIO-24+ family).

4. **Phase 6.3.8 broader adoption**
   - If a future paired qualification passes the gates, broad support
     target safety can be considered for adoption. Not the next step
     without evidence.

5. **Phase 7 (VGC RL training)**
   - Not approved. Do not start without explicit user authorization.

## Next immediate action

None required. The repo is in a stable handoff state. All open
threads are opt-in / not adopted / not approved.
