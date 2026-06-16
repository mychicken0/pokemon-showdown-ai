# Current Project State

Last updated: 2026-06-16 (Asia/Bangkok)

This file is the short handoff. It should answer: what is true now, what is
blocked, and what should happen next. For historical phase details, use
`walkthrough.md`. Source code and fresh command output always win over this
file.

## Repo

- Main repo: `/home/phurin/Program/Showdown_AI/pokemon-showdown-ai`
- Local Showdown repo: `/home/phurin/Program/Showdown_AI/pokemon-showdown`
- Battles must use local `localhost:8000` only.
- Known-good server command:

```bash
cd /home/phurin/Program/Showdown_AI/pokemon-showdown-ai
./scripts/start_local_showdown.sh
```

The script runs `./pokemon-showdown start --no-security` in the local
Showdown checkout. Keep that terminal/session open while watching battles in
the browser.

## Defaults

These defaults are intentional and should not be changed without a new
qualification:

```python
enable_ability_hard_safety_only = True
ability_hard_safety_block_score = 0.0
ability_hard_safety_direct_absorb_only = True
ability_hard_safety_allow_singleton_deduction = True

enable_support_move_target_hard_safety = False
enable_ally_heal_wrong_side_hard_safety = False
enable_voluntary_switch_quality_diagnostics = True
enable_voluntary_switch_quality_scoring = False

enable_priority_field_hard_safety = False
enable_known_ally_redirection_hard_safety = False
enable_switch_candidate_type_safety = False
enable_forced_switch_replacement_safety = False
enable_stale_target_after_ally_ko_safety = False
enable_stat_drop_switch_scoring = False

enable_ability_awareness = False
enable_meta_opponent_modeling = False
enable_random_set_opponent_modeling = False
enable_threat_tiebreaker = False
```

V2j fingerprint remains:
`a9fe97b3d2d08af70700eaa82e957d9a4d4e7330368f93bf0d81ea685bc302cb`.

## Current Decisions

### Random Doubles

- Canonical engine: `DoublesDamageAwarePlayer` in
  `bot_doubles_damage_aware.py`.
- Shared mechanics live in `doubles_mechanics.py`.
- Ability hard-safety is adopted.
- Broad support-target hard safety is **BLOCKED**.
  - Correct behavior, but paired performance gates failed.
  - Default stays `enable_support_move_target_hard_safety = False`.
- Narrow ally-heal wrong-side safety is **BLOCKED**.
  - It blocks Heal Pulse / Floral Healing / Decorate into opponent.
  - Repair audit found zero actual final OFF wrong-side selections, so there
    is no proven runtime bug to adopt against.
  - Default stays `enable_ally_heal_wrong_side_hard_safety = False`.
- Voluntary-switch quality scoring is **BLOCKED**.
  - Audit wiring is fixed and opportunities are now visible.
  - 6.4.10d had 2542 ON eligible turns but 0 selected voluntary switches.
  - The scoring rule is empirically a no-op in random doubles.
  - Default stays `enable_voluntary_switch_quality_scoring = False`.

### VGC 2026

- VGC preview chooses 4 from 6; post-preview battle decisions use the same
  canonical 2v2 engine as Random Doubles.
- Default preview policy remains `matchup_top4_v3`.
- `learned_preview_v3a` and `learned_preview_v3a1` are opt-in only.
- V3a.1 offline learner looked promising on validation, but labels were
  dominated by `basic_top4` and `random`; V3 had no decisive wins in that
  training set.
- V3a.2 reality check ran 20 pairs / 40 battles:
  - Learned vs V3 combined win rate: 20/40 = 50.0%.
  - Paired categories: learned_both 4, v3_both 4, split 12.
  - Plan change rate vs V3: 100%.
  - Mechanical GO for a larger qualification, but no superiority claim.

Phase V3 remains **not adopted**. The only justified next VGC step is a larger
paired qualification of `learned_preview_v3a1` vs `matchup_top4_v3`.

## Recommended Next Step

If the goal is to move VGC forward, run **Phase V3a.3**:

- 100-pair paired qualification.
- `learned_preview_v3a1` vs `matchup_top4_v3`.
- Localhost only.
- Browser-visible usernames and tags so the user can watch at
  `http://localhost:8000`.
- Predeclare gates before running:
  - 200 valid battles / 100 complete pairs.
  - zero timeout/error/no_battle.
  - preview validation 100%.
  - side collapse <= 10pp.
  - learned_both >= v3_both.
  - combined learned win rate >= 50%.
  - exact sign test and treatment CI reported, but no adoption claim unless
    the result is actually above noise.

If the goal is Random Doubles instead, do not keep requalifying blocked safety
flags. The useful next line is a small scoring-calibration task where selected
actions actually change.

## Working Tree

The worktree is expected to be dirty. Recent uncommitted lines include:

- V3a / V3a.1 / V3a.2 learned preview files and tests.
- Narrow ally-heal repair/audit files.
- Voluntary-switch probe, qualification, and analyzer files.
- Local server helper script.
- Documentation edits in `AGENTS.md`, `README.md`, `CURRENT_STATE.md`, and
  `walkthrough.md`.

Do not commit or push without explicit user authorization.

## Do Not Do

- Do not connect to the official Pokemon Showdown server.
- Do not silently flip default safety/scoring flags.
- Do not treat `walkthrough.md` historical claims as current truth without
  checking this file and source code.
- Do not stage generated files under `logs/` unless explicitly requested.
