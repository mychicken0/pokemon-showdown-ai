# Phase 6.3.8 — Support Move Target Hard Safety

**Date**: 2026-06-22
**Status**: `NARROW_FLAG_INTEGRATED_OPT_IN_ONLY`
**Phase**: 6.3.8 (broad was already wired; narrow was missing)

## Summary

Phase 6.3.8 has **two opt-in flags**:
- `enable_support_move_target_hard_safety` (broad) — was already wired into scoring
- `enable_ally_heal_wrong_side_hard_safety` (narrow, production-grade) — was
  defined and the helper `narrow_ally_heal_wrong_side_block` was imported
  but **not called in the scoring loop** (bug found in earlier verification)

This session **integrates the narrow flag into `score_action`** with the
smallest safe change:
- Independent `if` block placed directly after the broad check
- Uses the existing `narrow_ally_heal_wrong_side_block` helper
- Uses the existing `ally_heal_wrong_side_block_score` (separate from broad)
- Records the same audit fields (`_support_target_wrong_side_blocked`,
  `_support_target_block_reason`) so existing audit consumers work
- Does NOT bypass or weaken the broad safety check
- Defaults remain `False` for both flags

## What is blocked when each flag is ON

### `enable_support_move_target_hard_safety = True` (broad, existing)

| Move kind | Target | Blocked? |
|-----------|--------|----------|
| Ally-only (Heal Pulse, Floral Healing, Decorate) | opponent | **YES** |
| Ally-only | ally | No |
| Self-only (Recover, Substitute) | opponent/ally | **YES** (target != self) |
| Self-only | self | No |
| Opponent-disruptive (Taunt, Encore) | ally/self | **YES** |
| Opponent-disruptive | opponent | No |
| Pollen Puff (damaging/dual-purpose) | any | No |
| Field/team/either (Surf, Earthquake) | any | No |
| Damaging moves | any | No (unless dual-purpose) |

### `enable_ally_heal_wrong_side_hard_safety = True` (narrow, NEW integration)

Only blocks the 3 specific narrow moves:
- Heal Pulse aimed at opponent
- Floral Healing aimed at opponent
- Decorate aimed at opponent

This is the **production-grade replacement** that fixes the actual severe
bug (healing an opponent) without penalizing general opponent-disruption
choices (Taunt, Encore, Thunder Wave, etc.) or dual-purpose moves
(Pollen Puff, Skill Swap).

The narrow check fires **independently** of the broad flag. If both are on,
the broad check fires first and short-circuits before the narrow check
runs (narrow never reached). If only the narrow flag is on, the narrow
check fires alone.

## What is intentionally NOT blocked

- Damaging moves targeting allies (some formats allow)
- Ambiguous moves (target rules not clearly known)
- Anything based on species
- Anything based on unrevealed ability
- Weather/Terrain setters (raindance, sunnyday, etc.)
- Protect/Detect-style self moves (handled elsewhere)
- Skill Swap (ambiguous side, intentionally not classified)
- Pollen Puff (dual-purpose: damages opponent, heals ally)
- Taunt/Encore (narrow allowlist: only Heal Pulse/Floral Healing/Decorate)

## Exact narrow integration added

In `showdown_ai/bot_doubles_damage_aware.py`, directly after the broad
support target safety check (around line 6774):

```python
# Phase 6.3.8a: Narrow Ally-Heal Wrong-Side Hard Safety
# Production-grade replacement that only blocks Heal Pulse,
# Floral Healing, and Decorate aimed at an opponent.
# Independent of the broad flag — fires whether the broad
# flag is on or off. The broad flag (above) handles the
# wider wrong-side set first; this is a strict narrow subset.
if self.config.enable_ally_heal_wrong_side_hard_safety:
    blocked_narrow, reason_narrow = narrow_ally_heal_wrong_side_block(
        order, active_idx, battle, config=self.config
    )
    if blocked_narrow:
        if self.verbose:
            print(f"[Narrow Ally Heal Block] {reason_narrow}")
        self._support_target_wrong_side_blocked[battle_tag][
            active_idx
        ] = True
        self._support_target_block_reason[battle_tag][active_idx] = (
            reason_narrow
        )
        return float(self.config.ally_heal_wrong_side_block_score)
```

## Tests added

In `tests/test_doubles_support_move_target_safety.py`, new class
`TestScoreActionNarrowAllyHealTarget` with 9 tests:

| Test | Asserts |
|------|---------|
| `test_narrow_flag_off_default_unchanged` | flag OFF → narrow path skipped |
| `test_narrow_flag_on_blocks_healpulse_at_opponent` | flag ON + Heal Pulse at opp → blocked |
| `test_narrow_flag_on_blocks_floralhealing_at_opponent` | flag ON + Floral Healing at opp → blocked |
| `test_narrow_flag_on_blocks_decorate_at_opponent` | flag ON + Decorate at opp → blocked |
| `test_narrow_flag_on_allows_healpulse_at_ally` | flag ON + Heal Pulse at ally → not blocked |
| `test_narrow_flag_on_does_not_block_taunt_at_ally` | flag ON + Taunt at ally → not in narrow allowlist |
| `test_narrow_flag_on_does_not_block_pollen_puff` | flag ON + Pollen Puff → not in narrow allowlist |
| `test_broad_flag_unchanged_when_narrow_off` | broad only → existing behavior |
| `test_broad_and_narrow_both_on_block_healpulse_at_opponent` | both on → broad fires first |

## Tests run and results

| Test file | Tests | Result |
|-----------|------:|--------|
| `tests/test_doubles_support_move_target_safety.py` | 91 | **PASS** (was 82, +9 new) |
| `tests/test_doubles_engine_support_targets.py` | 67 | **PASS** |
| `tests/test_doubles_ability_hard_safety.py` | 86 | **PASS** |
| `tests/test_doubles_anti_setup_eligibility.py` | 51 | **PASS** |
| `tests/test_doubles_anti_setup_disruption.py` | 19 | **PASS** |
| `tests/test_doubles_accuracy2_self_ally_block.py` | 9 | **PASS** |
| **Total** | **323** | **PASS** |

## Defaults (UNCHANGED)

```python
# Per CURRENT_STATE.md and AGENTS.md
enable_support_move_target_hard_safety: bool = False  # broad
support_move_wrong_side_block_score: float = 0.0
enable_ally_heal_wrong_side_hard_safety: bool = False  # narrow
ally_heal_wrong_side_block_score: float = 0.0
```

Both flags remain **OFF by default**. No flip occurred.

## Adoption status

- Broad flag (`enable_support_move_target_hard_safety`): **OPT-IN ONLY / NOT PROMOTED**
  - Per CURRENT_STATE.md: "paired performance gates failed"
  - Repair audit found 0 actual final OFF wrong-side selections
- Narrow flag (`enable_ally_heal_wrong_side_hard_safety`): **OPT-IN ONLY / NOT PROMOTED**
  - Per CURRENT_STATE.md: "no proven runtime bug to adopt against"
  - Same evidence as broad: 0 wrong-side selections in audit

## Constraints respected

- ✅ No commit, no push (per task)
- ✅ No default flag flipped
- ✅ No WT scoring change (Weather/Terrain untouched)
- ✅ No Anti-Trick-Room behavior change
- ✅ No species-based Magic Bounce deduction
- ✅ No ability inference from species
- ✅ test_51 untouched
- ✅ No official Pokémon Showdown servers
- ✅ No broad 100-pair benchmark re-run
- ✅ `git diff --check` clean
- ✅ Paired-test root path failures left untouched (per task)

## Files changed

- `showdown_ai/bot_doubles_damage_aware.py` — added narrow flag check (12 lines)
- `tests/test_doubles_support_move_target_safety.py` — added narrow integration tests (~150 lines)
- `logs/phase6_3_8_support_move_target_hard_safety.md` — updated this log

## Verification commands

```bash
# Main support move tests (91 pass, +9 new)
python -m unittest tests.test_doubles_support_move_target_safety
# Ran 91 tests in 0.100s - OK

# Helper unit tests
python -m unittest tests.test_doubles_engine_support_targets
# Ran 67 tests in 0.080s - OK

# Related hard safety
python -m unittest tests.test_doubles_ability_hard_safety
# Ran 86 tests in 0.398s - OK

# Anti-setup
python -m unittest tests.test_doubles_anti_setup_eligibility
python -m unittest tests.test_doubles_anti_setup_disruption

# Self/ally accuracy block
python -m unittest tests.test_doubles_accuracy2_self_ally_block
```

## Recommendation

- **DO NOT** flip `enable_support_move_target_hard_safety` to True
- **DO NOT** flip `enable_ally_heal_wrong_side_hard_safety` to True
- Both flags remain opt-in
- Phase 6.3.8 is **closed and verified**; no further action needed
- This sub-task (6.3.8a) wires the narrow flag into scoring without
  changing defaults

## Remaining TODOs (not introduced by this session)

1. **3 pre-existing test failures in `test_doubles_support_move_target_safety_paired`**
   (test path issues from root → showdown_ai/ migration)
   - Per task: do not fix in this task
2. **No benchmark or large-pair run** — narrow flag integration verified
   only at the unit-test level
