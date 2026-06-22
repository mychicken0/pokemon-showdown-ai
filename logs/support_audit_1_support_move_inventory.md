# SUPPORT-AUDIT-1 — Support Move Inventory / Status Map

**Date**: 2026-06-22
**Status**: `INVENTORY_COMPLETE`
**Phase**: SUPPORT-AUDIT-1 (audit/documentation only, no behavior change)

## Summary Decision

This is a read-only audit that maps every currently relevant support-move
system in the project to one of ten status classes. The audit confirms
the **mechanics / safety correctness** path is well-covered (broad + narrow
wrong-side safety; revealed-only ability tracking; anti-TR mechanics;
Aroma Veil + Mold Breaker bypass). The **strategy / positive scoring**
path is **sparse** for most support categories — the bot can usually
block a clearly bad support move, but rarely has a positive scoring
bonus to actually pick a good one at the right time.

Two distinct gaps dominate the inventory:

1. **No `WT-*` follow-on work has been started** since the WT-1 and
   WT-2 audits closed as `SWITCH_SCORING_GAP_CONFIRMED` /
   `SWITCH_SCORING_GAP_CONFIRMED`. Weather/Terrain scoring calibration
   (WT-3 type boosts, WT-4 setter moves) is **future work**, not
   approved, not started.
2. **Anti-setup disruption, speed-setup, spread-defense scoring are
   all opt-in** (`enable_anti_setup_disruption_intent`,
   `enable_setup_intent_policy`, `enable_spread_defense_bonus`,
   `enable_protect_threat_refinement`) with default OFF. They are
   wired, unit-tested, and benchmark-tested, but they are not
   the default path.

Per the task scope, this is a documentation-only audit. No production
behavior, scoring, defaults, or tests were changed. No commit, no
push.

## Audit Method

1. Read `AGENTS.md`, `CURRENT_STATE.md`, `walkthrough.md`,
   `showdown_ai/bot_doubles_damage_aware.py`,
   `doubles_engine/support_targets.py`, `showdown_ai/ability_rules.py`,
   and the recent logs.
2. Walk the config flags in `DoublesDamageAwareConfig` and
   classify each by opt-in / default / scored / safety-only.
3. Walk the support-move allowlists in
   `doubles_engine/support_targets.py` and cross-reference with the
   scoring path in `bot_doubles_damage_aware.py`.
4. For each group, classify into one of the ten status classes
   defined by the task.

No code was read for behavior; all classifications are
path-walking-only. No new tests were added.

## Global Findings

- The mechanics / safety correctness path is **well-covered**:
  broad support wrong-side block, narrow ally-heal wrong-side
  block, revealed-only Magic Bounce / Good as Gold / Aroma Veil
  tracking, Mold Breaker / Teravolt / Turboblaze bypass, and
  CONTROL-PRIORITY-2A target-aware ability checks.
- The strategy / positive scoring path is **sparse** for support
  moves. Most "support" categories are detected and blocked when
  wrong, but rarely positively chosen.
- The `enable_protect` default is `True`; it is the only support
  flag with default ON. All other support-related scoring flags are
  default OFF.
- A small number of moves (Follow Me, Rage Powder, screens,
  hazards) are not in any allowlist and not in any scoring path.
  They are handled by generic damage / status scoring only.
- The audit does not propose any default flip. All opt-in flags
  remain opt-in.

## Inventory Table

| Group | Moves / Systems | Implementation | Flag | Default | Tests | Status | Gap | RL-data readiness | Next action |
|---|---|---|---|---|---|---|---|---|---|
| Target-side safety | broad wrong-side block | `doubles_engine.support_targets.support_move_wrong_side_block` + `bot_doubles_damage_aware.py:6760` | `enable_support_move_target_hard_safety` | OFF | 91 (`test_doubles_support_move_target_safety`) + 67 (`test_doubles_engine_support_targets`) | `blocked_not_promoted` (paired gates failed) | No real ON vs OFF signal in audit; both flags are opt-in | Mechanics safety is correct and RL-safe; positive scoring is not the goal | Keep opt-in. No default flip. Re-qualify paired gates before any flip. |
| Target-side safety | narrow ally-heal wrong-side block | `doubles_engine.support_targets.narrow_ally_heal_wrong_side_block` + `bot_doubles_damage_aware.py:6781` (wired in 6.3.8a) | `enable_ally_heal_wrong_side_hard_safety` | OFF | 91 + 67 + 9 (added in 6.3.8a) | `wired_default_off` (adoption still BLOCKED per CURRENT_STATE) | Same as above; the narrow path is the strict subset of the broad | Mechanics safety is correct and RL-safe | Keep opt-in. No default flip. |
| Target-side safety | Heal Pulse | classified as `_SUPPORT_ALLY_BENEFICIAL_SINGLE` in `support_targets.py` | n/a (uses broad/narrow flag) | OFF (flag-gated) | 91 (broad tests) + 67 (narrow tests) | `mechanics_safety_only` (the bot can block wrong-side but no positive scoring) | No positive strategy to use Heal Pulse at the right time | Safe for RL data: any wrong-side selection is hard-blocked | Future: add a positive bonus when ally is at low HP and survival guard passes |
| Target-side safety | Floral Healing | same as Heal Pulse | same | same | same | `mechanics_safety_only` | same | same | same |
| Target-side safety | Decorate | same as Heal Pulse | same | same | same | `mechanics_safety_only` | same | same | same |
| Target-side safety | ally-only / opponent-only / self-only / field | `classify_support_move_target_intent` classifies by `move.target` metadata + `_SUPPORT_*` allowlists | n/a (uses broad flag) | OFF (flag-gated) | covered by 91 broad tests | `mechanics_safety_only` | No positive scoring bonus for any classification; only the wrong-side block | Safe for RL data; broad wrong-side block is bit-for-bit | Future: positive scoring for "right" side is a separate decision |
| Ability / mechanics safety | Magic Bounce | `ability_rules.should_avoid_status_into_ability` + `bot_doubles_damage_aware.py` mechanics block (revealed-only) | covered by `enable_ability_hard_safety_only = True` (default) | safety default ON; no positive scoring path | 86 (`test_doubles_ability_hard_safety`) | `mechanics_safety_only` (revealed-only; pre-reveal Magic Bounce is not inferred) | No species-based deduction. No singletons outside the approved `ability_hard_safety_allow_singleton_deduction` flag | Safe for RL data: revealed-only; pre-reveal cases fall back to damage scoring | None. Leave as is. |
| Ability / mechanics safety | Good as Gold | `should_avoid_status_into_ability` returns True if `target_ability == "goodasgold"` | covered by ability hard safety | safety default ON | 86 | `mechanics_safety_only` | same as Magic Bounce | safe for RL data | None |
| Ability / mechanics safety | Aroma Veil (ally-side) | `ability_rules.ally_has_aroma_veil` + `should_avoid_status_into_ability` Aroma-Veil-specific path | covered by ability hard safety | safety default ON | 86 | `mechanics_safety_only` | Only blocks Taunt/Encore/Disable per Showdown mechanics | safe for RL data | None |
| Ability / mechanics safety | revealed-only ability tracking | `ability_rules.get_known_ability` + `bot_doubles_damage_aware._get_pokemon_ability_safe` | covered by ability hard safety + `ability_hard_safety_allow_singleton_deduction` | safety default ON | 86 | `mechanics_safety_only` | Pre-reveal unknown; pre-reveal singletons are not inferred (per AGENTS.md) | safe for RL data | None |
| Ability / mechanics safety | Taunt / Encore / Disable mechanics block | `should_avoid_status_into_ability` (status category check) | covered by ability hard safety | safety default ON | 86 | `mechanics_safety_only` (block bad use) | also covered by `_SUPPORT_OPPONENT_DISRUPTIVE_SINGLE` allowlist | safe for RL data | None (separate positive scoring below) |
| Anti-setup / disruption | Taunt | classified in `_SUPPORT_OPPONENT_DISRUPTIVE_SINGLE`; `enable_anti_setup_disruption_intent` opt-in bonus (Phase CONTROL-4B) | `enable_anti_setup_disruption_intent` | OFF | 51 (`test_doubles_anti_setup_eligibility`) + 19 (`test_doubles_anti_setup_disruption`) | `wired_default_off` | Positive scoring exists only with the opt-in flag | safe for RL data: helper uses revealed-only signals; no species inference | Future: consider promotion if benchmark gates pass. Not in this phase. |
| Anti-setup / disruption | Encore | same as Taunt | same | same | same | same | same | safe for RL data | same |
| Anti-setup / disruption | Disable | same as Taunt | same | same | same | same | same | safe for RL data | same |
| Anti-setup / disruption | Quash (anti-setup TARGETS) | classified in `ANTI_SETUP_TARGETS` in `bot_doubles_anti_setup_eligibility`; also subject to anti-setup bonus | same | same | same | same | same | safe for RL data | same |
| Anti-setup / disruption | Haze / Clear Smog (anti-stat-setup) | not in any allowlist in `doubles_engine.support_targets`; not in `ANTI_SETUP_TARGETS`; not in `STAT_BOOST_MOVES` (which is for detection, not blocking) | n/a | n/a | not covered by current tests | `mechanics_safety_only` (no positive scoring, no wrong-side block) | No detection of opp stat-boost setup beyond `STAT_BOOST_MOVES` used by `anti_setup_eligible`; Haze/Clear Smog are not scored as positive choices | safe for RL data: Haze is field-side, Clear Smog is single-target on opp; both are damage/status moves that fall under generic scoring | Future: add Haze/Clear Smog to `_SUPPORT_EITHER_MOVE_IDS` (similar to Skill Swap) for anti-stat-setup |
| Anti-setup / disruption | anti-Trick-Room status | `enable_anti_trick_room_response` opt-in bonus in `bot_doubles_damage_aware.py:4857` (CONTROL-PRIORITY-2E/2F) | `enable_anti_trick_room_response` | OFF | 15 (`test_target_aware_anti_tr`) | `blocked_not_promoted` (paired gates failed; -6pp regression at unknown Magic Bounce target) | Anti-TR Taunt on unknown Magic Bounce → self-Taunt damage (documented) | safe for RL data: revealed-only target logic; no species inference; mechanics safety is correct | None. User has decided to leave opt-in. |
| Protection / stall / defensive support | Protect / Detect | `enable_protect = True` (default ON) + `enable_protect_threat_refinement` opt-in | `enable_protect` | ON (default) | covered by `test_diagnose_protect_usage` | `handled_default` | Anti-overcommit penalty exists; threat refinement is opt-in | safe for RL data: scoring is non-targeting; no positive-strategy risk | None. Default is correct. |
| Protection / stall / defensive support | Wide Guard | `enable_spread_defense_bonus` opt-in + `wide_guard_spread_pressure_bonus` | `enable_spread_defense_bonus` | OFF | 67 + 91 (broad tests) | `wired_default_off` | Only positive scoring exists with the opt-in flag | safe for RL data: blocking is generic spread-defense; positive bonus is opt-in | Future: consider promotion if paired gates pass. Not in this phase. |
| Protection / stall / defensive support | Quick Guard | `_SUPPORT_*` allowlist does not include Quick Guard; `priority_blocked_by_psychic_terrain` covers Psychic Terrain priority block | n/a | n/a | not directly covered | `mechanics_safety_only` (no positive scoring) | Quick Guard is a normal priority-protect move; treated as a protect variant | safe for RL data | None. |
| Protection / stall | Crafty Shield | referenced in `bot_doubles_damage_aware.py:3262` as priority-protect alongside Fake Out / Quick Guard / Wide Guard | n/a | n/a | partially covered | `mechanics_safety_only` | No positive scoring | safe for RL data | None. |
| Protection / stall | Follow Me / Rage Powder | not in any allowlist; not scored as positive | n/a | n/a | not covered | `unknown_needs_probe` (no detection, no block, no score) | If a real battle has Follow Me opp, the bot does not currently use it as a positive strategy and does not block ally-targeted spread | safe for RL data (no current scoring) | Future: consider adding Follow Me / Rage Powder to a `_SUPPORT_ALLY_BENEFICIAL_ALLIES` allowlist (positive strategy) |
| Protection / stall | screens (Light Screen / Reflect) | not in any allowlist; not in scoring | n/a | n/a | not covered | `unknown_needs_probe` | Same as Follow Me | safe for RL data | Future: add screens if a future test team uses them |
| Speed / turn control | Tailwind | `enable_setup_intent_policy` opt-in + `setup_intent_speed_setup_bonus` | `enable_setup_intent_policy` | OFF | 34 (`test_doubles_setup3a_speed_intent`) | `wired_default_off` | Positive scoring exists only with opt-in | safe for RL data: detected by `has_tailwind(side_conditions)`; no species inference | Future: consider promotion if paired gates pass. Not in this phase. |
| Speed / turn control | Trick Room | same as Tailwind (same `enable_setup_intent_policy` opt-in) | same | same | same | `wired_default_off` | same | safe for RL data: detected by side_conditions | same |
| Speed / turn control | Icy Wind / Electroweb (speed-control support) | not in any allowlist; not scored as positive | n/a | n/a | not covered | `unknown_needs_probe` (no detection, no block, no score) | Icy Wind / Electroweb are damaging moves with side-effect speed debuff; treated as damage | safe for RL data | Future: consider if speed-control support should be a positive strategy |
| Speed / turn control | priority-blocking interactions | `priority_blocked_by_psychic_terrain` and `enable_speed_priority_awareness` | `enable_speed_priority_awareness` | True (default) | covered indirectly by speed/priority tests | `handled_default` | Default ON; correct detection | safe for RL data | None. Default is correct. |
| Weather / Terrain | Rain Dance | in `doubles_engine.support_targets`? **No** — not in any allowlist. Detected in audit state_snapshot | n/a (no positive scoring) | n/a | WT-2 audit | `scoring_gap_confirmed` (no setter selection) | No setter move scoring; no type-boost scoring (WT-3 future) | safe for RL data: no scoring means no positive-strategy risk | Future: WT-3 (type boost) and WT-4 (setter move scoring) are deferred, not approved |
| Weather / Terrain | Sunny Day | same as Rain Dance | n/a | n/a | WT-2 audit | same | same | same | same |
| Weather / Terrain | Sandstorm | same as Rain Dance (no allowlist, no scoring) | n/a | n/a | WT-2 audit | same | same | same | same |
| Weather / Terrain | Snowscape / Hail | not in allowlist, not in scoring | n/a | n/a | not covered | `unknown_needs_probe` (rare moves) | same | safe for RL data | Future: cover if test teams use it |
| Weather / Terrain | Electric Terrain | in WT-2 audit team (Jolteon) | n/a | n/a | WT-2 audit | same as Rain Dance | same | same | same |
| Weather / Terrain | Psychic Terrain | priority-blocking covered (`priority_blocked_by_psychic_terrain`); setter covered (Espathra in WT-2 team) | `enable_speed_priority_awareness` (default ON) | n/a (setter no scoring) | covered by `enable_speed_priority_awareness` | `handled_default` (priority block) + `scoring_gap_confirmed` (setter) | same as Rain Dance | safe for RL data | same |
| Weather / Terrain | Grassy Terrain | in WT-2 audit team (Rillaboom) | n/a | n/a | WT-2 audit | same as Rain Dance | same | same | same |
| Weather / Terrain | Misty Terrain | not in allowlist, not in scoring | n/a | n/a | not covered | `unknown_needs_probe` (rare) | rare move | safe for RL data | Future: cover if test teams use it |
| Weather / Terrain | ability setters (Drizzle / Sand Stream / Grassy Surge / Psychic Surge) | auto-set on switch via poke-env protocol; detected in `state_snapshot.weather` / `state_snapshot.fields`; no positive scoring on the setter mon | n/a | n/a | WT-1 / WT-2 audits; `test_doubles_priority_field_hard_safety` (Psychic Surge) | `handled_default` for detection; `scoring_gap_confirmed` for positive strategy | Bot detects correctly, responds via switch (not move) | safe for RL data | None for detection. WT-3/4 for positive scoring are deferred. |
| Weather / Terrain | WT-2 setter audit conclusion | `logs/phaseWT2_setter_audit.md` | n/a | n/a | WT-2 audit | `scoring_gap_confirmed` | confirmed gap: 31/71 setter-legal turns, 0/71 setter selected | safe for RL data | None. WT-3/4 deferred, not approved. |
| Healing / buff / ally support | Heal Pulse | same as Target-side safety above | same | same | same | same | same | safe for RL data | same |
| Healing / buff / ally support | Floral Healing | same | same | same | same | same | same | same | same |
| Healing / buff / ally support | Decorate | same | same | same | same | same | same | same | same |
| Healing / buff | Helping Hand | in `_SUPPORT_ALLY_BENEFICIAL_ALLIES` allowlist (`bot_doubles_anti_setup_eligibility` and `support_targets`); not in main bot's positive scoring path | n/a | n/a | covered by `test_doubles_engine_support_targets` | `mechanics_safety_only` (no positive scoring) | No positive scoring bonus | safe for RL data: target-side safety is correct | Future: positive scoring for "right" side is a separate decision |
| Healing / buff | Coaching | in `_SUPPORT_ALLY_BENEFICIAL_ALLIES` allowlist | n/a | n/a | same | same | same | safe for RL data | same |
| Healing / buff | Pollen Puff | special: dual-purpose (damages opp, heals ally) | n/a | n/a | covered by 67 engine tests + 91 broad tests | `mechanics_safety_only` (no positive scoring; correct target-side handling) | No positive scoring for either side; just preserved as dual-purpose | safe for RL data: dual-purpose preserved | None |
| Healing / buff | Life Dew | in `_SUPPORT_ALLY_BENEFICIAL_ALLIES` allowlist | n/a | n/a | covered by `test_doubles_engine_support_targets` | `mechanics_safety_only` | No positive scoring | safe for RL data | Future: positive scoring if used in test teams |
| Field / side control | screens (Light Screen / Reflect) | not in allowlist, not in scoring | n/a | n/a | not covered | `unknown_needs_probe` | rare in random doubles | safe for RL data | Future: cover if test teams use it |
| Field / side control | hazards | not in allowlist, not in scoring | n/a | n/a | not covered | `unknown_needs_probe` | rare in random doubles | safe for RL data | Future: cover if test teams use it |
| Field / side control | Mist / Safeguard | not in allowlist, not in scoring | n/a | n/a | not covered | `unknown_needs_probe` | rare in random doubles | safe for RL data | Future: cover if test teams use it |
| Field / side control | side condition moves (general) | detected via `side_conditions`; no positive scoring | n/a | n/a | partial | `mechanics_safety_only` (detection) | No positive scoring | safe for RL data | None for detection |

## Target-Side Safety

Implemented in `doubles_engine.support_targets` and wired into
`bot_doubles_damage_aware.score_action` (lines 6760-6773 broad, 6781-6794 narrow).

- **Broad** (`enable_support_move_target_hard_safety`): blocks any
  status move whose intended side (per `_SUPPORT_*` allowlists + `move.target`
  metadata) does not match the actual target side. Default OFF. Paired
  qualification gates failed (per CURRENT_STATE.md). Opt-in only.
- **Narrow** (`enable_ally_heal_wrong_side_hard_safety`): strict
  subset of the broad path; only blocks Heal Pulse / Floral Healing /
  Decorate aimed at an opponent. Wired in Phase 6.3.8a. Default OFF.
  Joint selection cannot resurrect a blocked narrow action.

Coverage: 91 broad tests + 67 engine tests + 9 narrow integration tests
(in Phase 6.3.8a). The 93 paired tests are also green after Phase 6.3.9
path-hygiene fix.

## Ability / Mechanics Safety

Implemented in `showdown_ai/ability_rules.py` and wired into
`bot_doubles_damage_aware.score_action` via `ability_hard_blocks_move`,
`direct_known_absorb_blocks_move`, `is_opponent_spread_move`, and
`ability_redirects_single_target_move`.

- **Magic Bounce** / **Good as Gold** / **Aroma Veil** are detected
  via revealed-only ability tracking. Pre-reveal singletons are not
  inferred unless `ability_hard_safety_allow_singleton_deduction = True`
  is set. Per AGENTS.md, the user has decided to leave Magic Bounce
  pre-reveal inference OFF (CONTROL-PRIORITY-2F).
- **Mold Breaker / Teravolt / Turboblaze** bypass is implemented
  (attacker's known ability disables target's ability during move
  execution).
- **Soundproof** and **Overcoat** block sound/powder-based status
  moves respectively.
- **Light Screen / Reflect** are NOT in the allowlist or scoring.

Coverage: 86 tests in `test_doubles_ability_hard_safety`. The
Aroma Veil / Mold Breaker / Magic Bounce paths are unit-tested.

## Anti-Setup / Disruption

Implemented in `showdown_ai.bot_doubles_anti_setup_eligibility` (helper
+ dry-run analyzer) and wired into `bot_doubles_damage_aware.score_action`
via `_anti_setup_disruption_eligible` (lines 4707+).

- **Taunt / Encore / Disable / Quash** are in `ANTI_SETUP_TARGETS`
  (4-move allowlist). The anti-setup disruption bonus is opt-in
  (`enable_anti_setup_disruption_intent = False`).
- **Haze / Clear Smog** are NOT in any allowlist; they are not
  blocked and not positively scored. This is an unknown but
  rare-move class.
- **anti-Trick-Room** is opt-in (`enable_anti_trick_room_response`),
  default OFF. The -6pp regression at unknown Magic Bounce is
  documented (CONTROL-PRIORITY-2F). No species-based Magic Bounce
  deduction is added.

Coverage: 51 (`test_doubles_anti_setup_eligibility`) + 19
(`test_doubles_anti_setup_disruption`) + 15
(`test_target_aware_anti_tr`).

## Protection / Defensive Support

Implemented as opt-in scoring paths in `bot_doubles_damage_aware`:

- **Protect / Detect** is the only support flag with default ON
  (`enable_protect = True`). Anti-overcommit penalty exists
  (`rs_enable_protect_overcommit_penalty`). Threat refinement is
  opt-in (`enable_protect_threat_refinement`).
- **Wide Guard** is opt-in (`enable_spread_defense_bonus`). The
  bonus is `wide_guard_spread_pressure_bonus` and only applies when
  the slot is in opp-spread pressure.
- **Quick Guard** and **Crafty Shield** are referenced in
  priority-protect handling but do not have a separate positive
  scoring path. They are treated as priority-protect variants.
- **Follow Me / Rage Powder** are not in any allowlist. They are
  not blocked, not positively scored. This is an unknown
  but rare-move class.
- **Screens** (Light Screen / Reflect) are not in any allowlist.
  They are rare in random doubles.

## Speed / Turn Control

Implemented in `bot_doubles_damage_aware.score_action` via
`_setup_intent_speed_setup_eligible` (lines 4424+).

- **Tailwind** and **Trick Room** are positively scored only when
  `enable_setup_intent_policy` is True. The bonus is
  `setup_intent_speed_setup_bonus` (default +450). Five guards apply.
- **Icy Wind / Electroweb** are not in any allowlist; they are
  treated as damaging moves. No positive scoring for the side-effect
  speed debuff.
- **Priority-blocking interactions** (e.g., Psychic Terrain
  blocking priority) are detected via
  `priority_blocked_by_psychic_terrain` and the
  `enable_speed_priority_awareness` flag (default ON).

Coverage: 34 tests in `test_doubles_setup3a_speed_intent`.

## Weather / Terrain

Per WT-1 and WT-2 audits:

- **Detection** is correct. `state_snapshot.weather` and
  `state_snapshot.fields` are populated correctly. The bot
  responds via switch (e.g., switch to Pelipper in rain) and
  type-boost damage scoring (Hurricane in rain, Psychic in
  Psychic Terrain).
- **Positive setter-move scoring** is NOT implemented. The bot
  never selects Rain Dance / Sunny Day / Grassy Terrain / Electric
  Terrain / Psychic Terrain / Misty Terrain as a positive strategy
  even when they are legal actions. WT-2 audit confirmed:
  31/71 setter-legal turns, 0/71 setter selected.
- **Type-boost scoring** for damage moves is partial: the bot
  has Hurricane / Psychic / etc. in `available_moves` but the
  scoring does not add a +50% type-boost bonus for them. WT-3
  (type-boost scoring calibration) is future work, not approved.
- **Ability-based setters** (Drizzle, Drought, Sand Stream,
  Snow Warning, Electric Surge, Grassy Surge, Misty Surge,
  Psychic Surge) auto-set on switch. The bot detects them in
  audit but does not have a positive strategy for them beyond
  the switch response.

Coverage: WT-1 (read-only audit, 0 selected settermoves) + WT-2
(setter audit, 3 battles, 71 turns, 0 setter selected). Per WT-2
audit, the conclusion is `SWITCH_SCORING_GAP_CONFIRMED`.

## Healing / Buff / Ally Support

Per the Target-side safety audit:

- **Heal Pulse** / **Floral Healing** / **Decorate** are
  classified as `_SUPPORT_ALLY_BENEFICIAL_SINGLE` and blocked
  from wrong-side targeting (broad + narrow flags). The bot has
  no positive scoring bonus to use these moves at the right time
  (e.g., when ally is at low HP). `mechanics_safety_only`.
- **Helping Hand** / **Coaching** / **Howl** / **Life Dew** are
  in `_SUPPORT_ALLY_BENEFICIAL_ALLIES`. The bot has no positive
  scoring path. `mechanics_safety_only`.
- **Pollen Puff** is dual-purpose (damages opp, heals ally) and is
  preserved as such. The bot has no positive scoring for either
  side; it is scored as a generic damaging move. `mechanics_safety_only`.

## Field / Side Control

- **Screens** (Light Screen / Reflect) are not in any allowlist
  and not in any scoring path. `unknown_needs_probe` (rare in
  random doubles).
- **Hazards** (Stealth Rock, Spikes, etc.) are not in any allowlist.
  `unknown_needs_probe` (rare in random doubles).
- **Mist** and **Safeguard** are not in any allowlist.
  `unknown_needs_probe` (rare in random doubles).
- **Side conditions in general** are detected via
  `battle.side_conditions` (e.g., tailwind already up). No
  positive scoring for setting them.

## RL-Readiness Notes

For an RL-data collection phase, the audit identifies the
following as RL-safe:

- **Mechanics safety is correct and bit-for-bit.** Wrong-side
  support blocks, ability-based status move blocks, and
  priority-field blocks are all in the scoring path and
  unit-tested.
- **Pre-reveal abilities are not inferred.** Magic Bounce,
  Good as Gold, Aroma Veil, and any other pre-reveal unknown
  abilities fall back to damage / status scoring. No species
  deduction. The CONTROL-PRIORITY-2F regression root cause is
  anti-TR Taunt on an unknown Magic Bounce target; the user
  has decided to leave this opt-in and accept the documented
  regression.
- **All opt-in flags are explicitly off by default.** A
  flip-the-flag experiment must be deliberate, gated, and
  scoped.

For an RL-data collection phase, the audit identifies the
following as **not** RL-safe (or not yet analyzed):

- **Follow Me / Rage Powder / screens / hazards / Mist /
  Safeguard / Icy Wind / Electroweb** are not in any allowlist
  and have no positive scoring. They are RL-safe in the sense
  that the bot does not score them positively (no positive
  strategy risk), but the bot also has no way to detect or
  block them. If the training data has these moves, the bot's
  behavior is "ignore them" which is not an RL signal.
- **Haze / Clear Smog** are not in any allowlist. They are rare
  in random doubles but should be considered for an
  anti-stat-setup allowlist.

The audit recommends: **before any RL-data collection phase,
add a "support move inventory log" to the training artifact
schema so that any new support move introduced in the training
data can be detected by an automatic `unknown_needs_probe`
flag.**

## Recommended Next Phases

After this audit, the following phases are candidates. None are
auto-started.

1. **`SUPPORT-3`: follow-me / rage-powder positive-strategy
   audit.** Decide whether Follow Me / Rage Powder should be
   added to a `_SUPPORT_ALLY_BENEFICIAL_ALLIES` allowlist with
   a positive scoring bonus. Risk: low. Effort: small.

2. **`SUPPORT-4`: anti-stat-setup audit.** Decide whether Haze /
   Clear Smog should be added to an anti-stat-setup allowlist.
   The risk is that the bot may need to detect opp stat-boost
   setup beyond the existing `STAT_BOOST_MOVES` used by
   `anti_setup_eligible`. Effort: small.

3. **`SUPPORT-5`: positive-strategy for Heal Pulse / Decorate.**
   When an ally is at low HP and survival guard passes, add an
   opt-in positive bonus to use these moves. Risk: low (only
   fires when ally HP is low and the bot can survive). Effort:
   small.

4. **`WT-3`: Weather/Terrain type-boost scoring calibration.**
   Future work, not approved. Not in this audit's scope.

5. **`WT-4`: setter-move scoring calibration.** Future work, not
   approved. Not in this audit's scope.

6. **`Phase 7`: VGC RL training.** Not approved per RL-8
   closeout. Not in this audit's scope.

## Constraints Respected

- ✅ No production behavior change
- ✅ No scoring change
- ✅ No default flip
- ✅ No test changes (audit-only)
- ✅ No benchmarks run
- ✅ No official Pokémon Showdown servers
- ✅ No commit (per task)
- ✅ No push (per task)
- ✅ No `test_51` touch
- ✅ No Anti-Trick-Room behavior change
- ✅ No Weather/Terrain behavior change
- ✅ No species-based Magic Bounce deduction
- ✅ No new behavior flag
- ✅ No new code (audit-only, single new log file)
- ✅ Anti-TR remains opt-in, no default flip
- ✅ Broad / narrow support wrong-side flags remain opt-in

## Files in this audit

- `logs/support_audit_1_support_move_inventory.md` (this file, new)

## Status of "TODO" from prior phases

- **Phase 6.3.9** TODO about 3 paired-test path failures: **RESOLVED**
  (commit `1dffc59`). 93/93 in `test_doubles_support_move_target_safety_paired`,
  337/337 in the targeted suite.

- **WT-2** TODO about Weather/Terrain scoring calibration
  (WT-3 / WT-4): **DEFERRED, not approved**. Documented in
  CURRENT_STATE.md and the WT-2 audit log.

- **Phase 6.3.8 broad adoption**: **DEFERRED**. Paired gates
  failed. No default flip.

- **V3a.3 VGC preview rerun**: **DEFERRED**. User has not
  authorized a rerun.
