# Phase SCENARIO-18 — Weakness Policy (Basic) — DEFERRED

## 1. Summary

**Decision**: ``DEFERRED_TO_LATER_FORMAT``.

SCENARIO-18 (``wp_super_effective_basic``)
could not be implemented in VGC 2026
Champions format because **Weakness
Policy is banned** (``isNonstandard:
Past``) in the Champions VGC 2026 mod.

## 2. Why deferred

The showdown data
(``data/mods/champions/items.ts``)
marks Weakness Policy as
``isNonstandard: "Past"``:

```typescript
weaknesspolicy: {
    inherit: true,
    isNonstandard: "Past",
},
```

When the showdown team validator
encounters a Pokemon with Weakness
Policy, it returns:

```
Your team was rejected for the following reasons:
- Dragonite's item Weakness Policy does not exist in Gen 9.
```

This is a real VGC 2026 design decision
(not a bug in our code or the
scenario). Similar items that activate
on super-effective hits are also
banned:

- Weakness Policy
- Absorb Bulb (Water-type boost)
- Cell Battery (Electric-type boost)
- Eject Button / Eject Pack

## 3. P2 readiness check (per SCENARIO-6 design)

The SCENARIO-6 design's P2 readiness
check said "0 WP holders in repo". The
actual issue is that **WP is banned
in VGC 2026 Champions format**, not
just that no curated team has it.

## 4. Implementation plan (deferred)

When ready to implement SCENARIO-18:

1. **Use a different format** (not
   VGC 2026 Champions). The poke-env
   bot must support the format.
2. **Use a substitute item** that
   activates on super-effective hit.
   As of Gen 9, there is no good
   substitute (all "free boost on
   hit" items are banned).
3. **Use a different mechanic** (e.g.,
   Weakness Policy was re-introduced
   in some games like Pokémon Legends
   Arceus).

## 5. P2 family status (post-SCENARIO-18 deferred)

| family | status |
|---|---|
| weather (P2) | ✓ DONE (SCENARIO-16) |
| beatup_justified (P2) | ✓ DONE (SCENARIO-17) |
| wp (P2) | DEFERRED (item banned) |

## 6. References

- ``logs/phaseSCENARIO6_library_design.md``
  — family plan
- ``logs/phaseSCENARIO15_p1_closeout.md``
  — P1 closeout
- ``data/mods/champions/items.ts`` —
  WP marked Past
- ``data/curated_teams/scenarios/wp_super_effective_basic.json``
  — scenario file (description updated
  to mark as DEFERRED)
- ``logs/phaseSCENARIO18_wp_super_effective_deferred_report.md``
  — this report

## 7. Final Summary

- **Decision**: ``DEFERRED_TO_LATER_FORMAT``.
- **Reasoning**:
  1. **Weakness Policy is banned in VGC
     2026 Champions** (``isNonstandard:
     Past``).
  2. **Similar items (Absorb Bulb, Cell
     Battery, Eject Button/Pack) are
     also banned** in the format.
  3. **The showdown team validator
     rejects WP** explicitly with
     "does not exist in Gen 9".
- **Top 3 findings**:
  1. WP banned in VGC 2026
  2. Similar items also banned
  3. Custom team was created but
     couldn't be tested
- **Exact next recommended phase**:
  depends on user priorities:
  - Other P2 families (none active)
  - Earthquake framework (P1, separate
    work)
