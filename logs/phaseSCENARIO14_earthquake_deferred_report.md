# Phase SCENARIO-14 — Spread Defense (Earthquake) — DEFERRED

## 1. Summary

SCENARIO-14 (``spread_def_earthquake``)
is **deferred** per the user's order
after SCENARIO-11 review and
SCENARIO-12/13 implementation.

**Decision**: ``DEFERRED_TO_LATER_PHASE``.

Earthquake has target semantics that
require additional handling:

- Earthquake is a Ground-type spread
  move that hits **all non-airborne
  Pokémon** on the field.
- Exceptions: Flying types, Levitate
  ability, Magnet Rise, Telekinesis,
  etc.
- The audit logger needs to track
  which mons are airborne vs grounded
  to determine if Earthquake actually
  hits the target.
- The script's ``_build_move_order``
  must check the opp's types/abilities
  to confirm the move is legal.

## 2. Why deferred (per user order)

Per the user's order after
SCENARIO-11 review:

> "อย่า Earthquake ก่อน เพราะ
> grounded/Levitate ทำให้ debug ยากกว่า"

The user explicitly asked to defer
Earthquake until after
``redir_followme_basic`` and
``spread_def_rock_slide`` are
validated. Rock Slide and Heat Wave
have simpler target semantics
(``allAdjacentFoes``, no type
filtering), so they can be implemented
without the audit / type / ability
complexities.

## 3. Why Earthquake is complex

### 3.1 Target filtering

Earthquake hits grounded targets.
Showdown's protocol indicates this
via the ``-immune`` field on the
damage event. The audit needs to
parse:

- ``|move|p1a: Tyranitar|Earthquake|
  p2a: ...|-immune|p2a: Rotom-Wash
  |[from] ability: Levitate``
- ``|-damage|p2a: Hatterene|...``

The audit's ``opponent_used_spread``
flag fires on any spread move
(already in the code via
``_OPP_SPREAD_LIKE``). But the
canonical signal via baseline
``scripted_actions`` is independent
of this — it just records the script
fired.

### 3.2 Bot response complications

For Earthquake, the bot's response is
more complex:

- Spread moves: still vulnerable to
  Earthquake (grounded ones).
- Wide Guard: protects all allies
  from the spread move (still works).
- Ground immunities: Rotom-Wash
  (Levitate), Volcarona (Flying? no,
  Bug/Fire). Different from Heat Wave
  (Fire) where Levitate doesn't help.

The bot's audit would need to track:

- Whether the bot's active mons are
  airborne (Flying type, Levitate
  ability, etc.)
- Whether Wide Guard was the chosen
  response

### 3.3 Framework changes required

For Earthquake to be a clean scripted
scenario, the framework would need:

1. **Audit logger extension**: track
   which mons are airborne (Flying
   type or Levitate ability). This
   is non-trivial because:
   - Flying type check needs type
     data per species.
   - Levitate ability check needs
     ability data per mon.
2. **Script helper**: confirm the
   scripted move is legal for the
   active mon (e.g., Tyranitar with
   Earthquake vs Tyranitar without).
3. **Validator extension**: check
   if the scripted move was actually
   effective (not immune).

These changes are out of scope for
the P1 basic probe series. They
should be deferred to a later phase
(Phase 3 of the implementation plan
per SCENARIO-11).

## 4. Implementation plan (deferred)

When ready to implement SCENARIO-14:

1. Add type/ability data lookup to
   the scripted player.
2. Add airborne detection (Flying
   type OR Levitate ability).
3. Add ``scripted_action_legal``
   check to the audit's
   ``scripted_actions``.
4. Add new validator type
   ``expected_scripted_action_effective``
   that checks the move is not
   immune.
5. Pick teams where Earthquake is
   not blocked (e.g., opp's mons are
   not all Levitate).
6. Run 1-pair probe.

## 5. P1 family status

| family | status |
|---|---|
| spread_def (Heat Wave) | ✓ DONE (SCENARIO-10) |
| spread_def (Rock Slide) | ✓ DONE (SCENARIO-13) |
| spread_def (Earthquake) | DEFERRED (SCENARIO-14) |
| redir (Rage Powder) | ✓ DONE (SCENARIO-12) |
| redir (Follow Me) | deferred to later |

## 6. References

| source | path | role |
|---|---|---|
| Library design | `logs/phaseSCENARIO6_library_design.md` | family plan |
| P1 review | `logs/phaseSCENARIO11_p1_review_spread_signal_gap_report.md` | SCENARIO-11 decision |
| Sibling (HW) | `data/curated_teams/scenarios/spread_def_heat_wave.json` | basic variant |
| Sibling (RS) | `data/curated_teams/scenarios/spread_def_rock_slide.json` | RS variant |
| Sibling (RP) | `data/curated_teams/scenarios/redir_followme_basic.json` | redir variant |

## 7. Final Summary

- **Decision**: ``DEFERRED_TO_LATER_PHASE``.
- **Reasoning**:
  1. Per user order, Earthquake is
     deferred until after
     ``redir_followme_basic`` and
     ``spread_def_rock_slide`` are
     validated.
  2. Earthquake requires grounded /
     Levitate / Flying detection in
     the audit logger, which is a
     non-trivial framework change.
  3. Heat Wave and Rock Slide have
     simpler target semantics
     (``allAdjacentFoes``, no type
     filtering), so they can be
     implemented without the
     audit / type / ability
     complexities.
- **Top 3 findings**:
  1. **Earthquake is grounded-only**:
     requires Flying type / Levitate
     ability detection in the audit
     logger.
  2. **Framework changes needed**:
     type/ability data lookup,
     airborne detection,
     ``scripted_action_legal`` check,
     new validator type
     ``expected_scripted_action_effective``.
  3. **Implementation plan documented**:
     when ready, follow the 6-step
     plan in section 4.
- **Exact next recommended phase**:
  depends on user priorities:
  - More P1 spread variants
    (e.g., ``spread_def_dazzling_gleam``)
  - More P1 redir variants
    (e.g., ``redir_followme_basic``
    with actual Follow Me)
  - P2 family (beatup_justified,
    wp, weather) — needs custom teams
  - **Earthquake (this scenario)** —
    only when framework changes are
    budgeted
- **No scoring change. No commit
  yet. No ``test_51``. No
  ``learned_preview_v3d1``. No V3d.1
  PAUSE resumption.**
- **No ``logs/vgc2026_phaseV3d1_model.json``.**
- **Default state**: n/a (no impact
  when --scenario-file is not set).
