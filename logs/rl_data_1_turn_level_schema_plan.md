# RL-DATA-1 — Turn-Level Dataset Schema + Instrumentation Plan

**Date**: 2026-06-22
**Status**: `SCHEMA_PLANNED_NO_TRAINING`
**Phase**: RL-DATA-1 (schema / instrumentation planning only)

## Summary Decision

This is a docs-only planning phase. It does **not** train any model.
It does **not** collect a large dataset. It does **not** run battles
or benchmarks. It does **not** change production code, scoring,
defaults, or tests. It defines the future `turn_rl_v1.1` schema
(building on the existing `turn_rl_v1.0` from RL-4) and the
instrumentation work required before any RL training is
trustworthy.

RL training remains **not approved** per RL-8 closeout and per
AGENTS.md ("The current development line is Phase 6. Do not start
Phase 7 unless the user explicitly authorizes it."). This phase
plans the **prerequisites** for that future RL phase. It does not
start it.

The plan is to:

1. Reuse the existing `turn_rl_v1.0` schema from RL-4 as the base.
2. Extend it to `turn_rl_v1.1` with the support-move instrumentation
   fields required by SUPPORT-AUDIT-1.
3. Identify which existing audit fields already cover the new
   requirements.
4. Identify which fields are missing and would need a future
   RL-DATA-2 instrumentation phase.
5. Define data-quality gates that must pass before RL training.
6. Define an "unknown support move detector" that flags any new
   support move not present in the SUPPORT-AUDIT-1 inventory.

## Why RL Training Is Not Approved Yet

Per RL-8 closeout, RL training is gated on:

- **Policy bias.** The current audit reflects one policy's choices.
  Any offline RL on this data is constrained to imitate or improve
  over that policy. Off-policy evaluation is not yet available.
- **Sparse terminal rewards.** Win/loss is a sparse signal over
  5-15 turns. Credit assignment without a dense proxy is weak.
- **Off-policy evaluation missing.** We cannot yet measure
  "would a different joint action have won this battle?" except
  via the audit's existing counterfactual fields.
- **Credit assignment across two slots.** Joint actions couple
  two slots. Per-slot reward attribution needs a model or a
  heuristic that we have not validated.
- **Limited opponent action sequence.** The audit records our
  decision but only a brief `opp_actions` summary for the
  opponent. We do not have full opponent turn-by-turn
  trajectories to condition on.
- **No action-mask learning target.** The dataset stores the
  legal set per turn. Any behavior-cloning model needs a
  consistent action-mask representation that matches the
  inference-time action space.
- **Action distribution heavily biased toward double attacks.**
  Per PROTECT-1 roadmap, the action distribution is too
  attack-heavy for useful training. A pre-training audit of the
  action distribution is a prerequisite.
- **Support-move instrumentation missing.** Per SUPPORT-AUDIT-1,
  many support moves are `mechanics_safety_only` (blocked when
  wrong, no positive scoring) and several are `unknown_needs_probe`
  (Follow Me / Rage Powder / screens / hazards / Mist / Safeguard).
  An RL policy cannot be trusted on moves it cannot observe.
- **Pre-reveal Magic Bounce is not inferred.** Per AGENTS.md, no
  species-based Magic Bounce deduction is allowed. RL data
  collection must not include any pre-reveal singleton inference.
- **AGENTS.md constraint.** "The current development line is
  Phase 6. Do not start Phase 7 unless the user explicitly
  authorizes it." RL training is Phase 7.

## Existing RL / Dataset Artifacts Found

This phase reuses the following prior phase work:

- **RL-4** (`logs/phaseRL4_turn_level_offline_dataset_schema_design.md`):
  designed `turn_rl_v1.0` schema. 10 validation gates. Forbidden
  fields defined.
- **RL-5** (`logs/phaseRL5_turn_level_offline_dataset_builder_report.md`):
  `build_turn_level_offline_dataset.py` builder. 720 raw rows /
  574 deduped / 80 battles. 34 fixture tests, all pass.
- **RL-5b** (`logs/phaseRL5b_turn_level_dataset_builder_field_coverage_fix_report.md`):
  source-data limitation investigation. BI3M2 source was
  generated before BEHAVIOR-18 added fields. Builder is correct.
- **RL-6** (`logs/phaseRL6_turn_level_dataset_quality_report.md`):
  `analyze_turn_level_offline_dataset_quality.py` analyzer.
  READY_FOR_DRYRUN, 8/8 criteria pass. 20 fixture tests, all pass.
- **RL-7** (`logs/phaseRL7_offline_policy_dryrun_feasibility_report.md`):
  `dryrun_turn_level_offline_policy.py` dry-run. 42 fixture tests.
  Pipeline works but data is too attack-heavy.
- **RL-8** (`logs/phaseRL8_turn_level_offline_rl_closeout.md`):
  closed as `PIPELINE_WORKS / TRAINING_NOT_APPROVED`. No model
  artifact created. No production change. No battle runs.

Existing dataset:

- `logs/turn_level_offline_dataset_rl5b_v1_0_bi3m2.jsonl`
  (574 deduped rows, BI3M2 source)
- `logs/turn_level_offline_dataset_rl5b_v1_0_bi3m2_summary.json`
- `logs/turn_level_offline_dataset_rl5b_v1_0_bi3m2_validation.md`

Existing builder / analyzer / dry-run scripts:

- `showdown_ai/build_turn_level_offline_dataset.py` (RL-5)
- `showdown_ai/analyze_turn_level_offline_dataset_quality.py` (RL-6)
- `showdown_ai/dryrun_turn_level_offline_policy.py` (RL-7)

Existing tests:

- `tests/test_build_turn_level_offline_dataset.py` (RL-5, 34 + 8 = 42 tests)
- `tests/test_analyze_turn_level_offline_dataset_quality.py` (RL-6, 20 tests)
- `tests/test_dryrun_turn_level_offline_policy.py` (RL-7, 42 tests)

Existing support-move audit (this is for instrumentation planning, not
data):

- `logs/support_audit_1_support_move_inventory.md`
  (SUPPORT-AUDIT-1, current state)

Existing behavior-evidence audits:

- `logs/phaseBEHAVIOR2_turn_level_gap_seal_analysis.md`
  (speed-priority gap)
- `logs/phasePLANNER_DATA_1_dataset_report.md` (planner dataset)

## Dataset Goals

The future `turn_rl_v1.1` dataset must:

1. **Capture all existing audit fields** that RL-4 / RL-5 / RL-5b /
   RL-6 / RL-7 already produce.
2. **Add support-move instrumentation fields** per
   SUPPORT-AUDIT-1 categories.
3. **Add weather/terrain setter-move selection** and **type-boost
   selection** fields (currently `v4a_raw_scores_slot0` and
   `v4a_raw_scores_slot1` are `None`, so WT-3 / WT-4 calibration
   would also need a future instrumentation phase).
4. **Add action-distribution summary** at the battle level so
   that an RL training run can fail fast if the action
   distribution collapses (per PROTECT-1).
5. **Add off-policy-evaluation anchors** in the form of
   counterfactual fields (already partially present:
   `switch_counterfactual`).
6. **Preserve all RL-4 forbidden fields** as forbidden. No
   future-looking data, no hidden info, no species-based
   ability inference.
7. **Preserve RL-8 closeout** as the gatekeeper: no training
   until RL-DATA-2 (instrumentation) and a future RL-DATA-3
   (dataset build) phases pass.

## Non-Goals

- **No RL training.** Phase 7 is not approved.
- **No large dataset collection.** This phase plans the
  schema; a future RL-DATA-2 phase would do the actual
  collection.
- **No benchmark or battle runs.** This phase is docs-only.
- **No production code change.** No scoring change. No
  default flip.
- **No species-based Magic Bounce deduction.** Forbidden
  per AGENTS.md.
- **No new behavior flags.** This is a schema planning phase.
- **No Anti-Trick-Room behavior change.** Anti-TR remains
  opt-in.
- **No Weather/Terrain behavior change.** WT-2 is closed as
  `SWITCH_SCORING_GAP_CONFIRMED`; no scoring fix.

## Turn-Level Row Schema

The future `turn_rl_v1.1` row schema extends `turn_rl_v1.0`:

### 1. Battle metadata (existing in v1.0, preserved)

| field | type | description | status |
|---|---|---|---|
| `schema_version` | str | `"turn_rl_v1.1"` | existing |
| `dataset_id` | str | unique dataset identifier | existing |
| `episode_id` | str | unique battle identifier | existing |
| `battle_tag` | str | poke-env battle tag | existing |
| `battle_result` | str | `"win"` / `"loss"` / `"tie"` | existing |
| `turn_index` | int | 1-based turn number (player turn) | existing |
| `player_side` | str | `"p1"` / `"p2"` | existing |
| `total_turns` | int | total turns in the battle | existing |
| `policy_name` | str | policy that produced the audit | existing |
| `benchmark_arm` | str | treatment / baseline / control | existing |
| `source_artifact` | str | path to source JSONL | existing |
| `runtime_mode` | str | `"customgame"` / `"vgc"` | existing |
| `random_seed` | int | battle seed | existing |
| `config_hash` | str | hash of DoublesDamageAwareConfig | NEW in v1.1 — required so that an RL training run can detect config drift between rows |
| `format` | str | `"gen9randomdoublesbattle"` / `"gen9doublescustomgame"` / `"gen9vgc2026regi"` | existing (sometimes called `runtime_mode`) |
| `team_id` | str | local-only team id | existing |
| `opponent_team_id` | str | local-only opp team id | existing |
| `won` | bool | per-battle terminal | existing |
| `local_only_provenance` | bool | must be `True` always | NEW in v1.1 — must be asserted; any `False` row is forbidden for RL |

### 2. State snapshot (existing in v1.0, preserved)

| field | type | description | status |
|---|---|---|---|
| `state_snapshot` | dict | per-side active species / HP / boosts / items | existing |
| `state_snapshot.weather` | list[str] | current weather keys | existing |
| `state_snapshot.fields` | list[str] | current terrain keys | existing |
| `speed_priority_threatened` | bool | (RL-7+) BEHAVIOR-18 field | existing (was None in BI3M2) |
| `expected_to_faint_before_moving` | dict | per-slot expected-faint | existing (was None in BI3M2) |

Per the v1.0 design, all state fields must be **visible data only**
(no unrevealed abilities, no hidden item information, no
species-based inference).

### 3. Legal actions (existing in v1.0, preserved)

| field | type | description | status |
|---|---|---|---|
| `legal_action_keys_slot0` | list[str] | V2l.1 keys for slot 0 | existing |
| `legal_action_keys_slot1` | list[str] | V2l.1 keys for slot 1 | existing |
| `legal_joint_action_keys` | list[str] | V2l.1 keys for joint action | existing |
| `v4a_legal_action_keys_slot0` | list[str] | V4a 4-tuple keys (mechanic-aware) | existing |
| `v4a_legal_action_keys_slot1` | list[str] | V4a 4-tuple keys | existing |
| `total_legal_joint_orders` | int | count of legal joint actions | existing |
| `joint_order_count` | int | (RL-7+) joint-order count | existing (was 0% in BI3M2) |

### 4. Scoring trace (existing in v1.0, extended for v1.1)

| field | type | description | status |
|---|---|---|---|
| `selected_joint_key` | str | V2l.1 key of selected action | existing |
| `selected_per_slot` | dict | per-slot selected action | existing |
| `selected_score` | float | final score of selected action | existing |
| `top_5_alternatives` | list[str] | V2l.1 keys of top 5 alternatives | existing |
| `top_5_scores` | list[float] | scores of top 5 alternatives | existing |
| `final_action_keys` | list[str] | V2l.1 keys of final action | existing |
| `score_gap_selected_best_alt` | float | score gap between selected and best alt | existing |
| `v2l1_raw_scores_slot0` | dict | V2l.1 raw score per action (slot 0) | existing |
| `v2l1_raw_scores_slot1` | dict | V2l.1 raw score per action (slot 1) | existing |
| `v4a_raw_scores_slot0` | dict | V4a raw score per action (slot 0) | existing (was None in BI3M2) |
| `v4a_raw_scores_slot1` | dict | V4a raw score per action (slot 1) | existing (was None in BI3M2) |
| `damage_estimate` | dict | per-action damage estimate | NEW in v1.1 (optional; required only if a future training phase needs a dense reward proxy) |
| `protect_stall_score` | dict | per-action protect/stall score | NEW in v1.1 (optional; required only if Protect usage is a positive strategy in the trained policy) |
| `support_bonus` | dict | per-action positive support bonus | NEW in v1.1 (optional; see Support-Move Instrumentation Fields) |
| `safety_block_score` | float | score returned when action is safety-blocked | NEW in v1.1 (mirror of `ally_heal_wrong_side_block_score`, `support_move_wrong_side_block_score`) |
| `selected_rank` | int | rank of selected action among all candidates (1 = best) | NEW in v1.1 (so a trained policy can be measured on rank-quality) |
| `score_component_breakdown` | dict | per-component score (damage, support, safety, etc.) | NEW in v1.1 (optional; requires the bot to record per-component score; not currently recorded) |

### 5. Support move instrumentation (NEW in v1.1)

Per SUPPORT-AUDIT-1, every support move in the dataset must be
classified by group and status. The dataset must contain the
following per-action fields:

| field | type | description |
|---|---|---|
| `support_group` | str | one of: `target_side_safety`, `ability_mechanics_safety`, `anti_setup_disruption`, `protection_defensive_support`, `speed_turn_control`, `weather_terrain`, `healing_buff_ally_support`, `field_side_control`, `unknown_needs_probe` |
| `support_status_from_audit` | str | one of: `handled_default`, `handled_opt_in`, `wired_default_off`, `blocked_not_promoted`, `audit_only`, `scoring_gap_confirmed`, `no_positive_strategy`, `mechanics_safety_only`, `future_work`, `unknown_needs_probe` |
| `safety_only` | bool | `True` if the bot can block wrong-side but cannot positively score |
| `positive_strategy` | bool | `True` if the bot has a positive scoring bonus for this category (currently `False` for nearly all support moves) |
| `opt_in_flag_required` | str | name of the opt-in flag, e.g., `enable_anti_setup_disruption_intent`, or empty if not flag-gated |
| `default_enabled` | bool | whether the opt-in flag is default `True` |
| `block_reason` | str | reason string if the action was safety-blocked, else empty |

These fields must be **precomputed at dataset build time** (in the
RL-DATA-2 instrumentation phase) by cross-referencing the action's
move id against the SUPPORT-AUDIT-1 inventory. A naive
move-id-to-group mapping is acceptable for v1.1; a more accurate
metadata-aware mapping is a future improvement.

### 6. Safety and mechanics fields (existing in v1.0, preserved)

| field | type | description | status |
|---|---|---|---|
| `overkill_penalty_triggered` | bool | damage-overkill penalty | existing |
| `focus_fire_triggered` | bool | focus-fire bonus | existing |
| `stale_target_avoided` | bool | stale-target safety | existing |
| `narrow_ally_heal_candidate_blocked_slot0` | bool | narrow flag blocked | existing |
| `narrow_ally_heal_candidate_blocked_slot1` | bool | narrow flag blocked | existing |
| `switch_counterfactual` | dict | best_switch / chosen / delta / reason_codes | existing |
| `block_reason_wrong_side` | str | broad support wrong-side block | NEW in v1.1 (mirror of audit's `_support_target_block_reason`) |
| `block_reason_narrow_ally_heal` | str | narrow flag block | NEW in v1.1 (mirror of audit) |
| `block_reason_ability_hard_safety` | str | ability hard-safety block | NEW in v1.1 |
| `revealed_ability_source` | str | "revealed" / "singleton_deduction" / "unknown" | NEW in v1.1 (must be `"revealed"` or `"singleton_deduction"` only; `"species"` is FORBIDDEN) |
| `used_species_ability_inference` | bool | must always be `False`; any `True` row is a dataset contamination | NEW in v1.1 (mandatory assertion in v1.1 gates) |
| `impossible_target_detected` | bool | must always be `False`; any `True` row is a dataset contamination | NEW in v1.1 (mandatory assertion in v1.1 gates) |
| `blocked_action_resurrected_by_joint` | bool | must always be `False`; if a safety-blocked action was selected by joint selection, this is a safety bug | NEW in v1.1 (mandatory assertion in v1.1 gates) |

### 7. Weather / Terrain fields (NEW in v1.1)

Per WT-1 / WT-2 audits:

| field | type | description |
|---|---|---|
| `weather_current` | str | current weather (raindance, sunnyday, sandstorm, snowscape, hail, or empty) |
| `terrain_current` | str | current terrain (electricterrain, grassyterrain, mistyterrain, psychicterrain, or empty) |
| `weather_turns_remaining` | int | remaining turns (5 max, 8 with weather extender items) — optional |
| `terrain_turns_remaining` | int | remaining turns — optional |
| `setter_move_legal` | list[str] | setter moves in legal actions (raindance, sunnyday, etc.) — per slot |
| `setter_move_selected` | list[str] | setter moves selected by the bot — per slot |
| `setter_move_raw_score` | dict | raw score of each setter move — optional, requires v4a_raw_scores |
| `type_boost_move_legal` | list[str] | type-boost moves in legal actions (hurricane, psychic, etc.) |
| `type_boost_move_selected` | list[str] | type-boost moves selected |
| `type_boost_applied` | list[str] | moves whose type was boosted by weather/terrain at execution |
| `weather_terrain_scoring_status` | str | `scoring_gap_confirmed` / `future_work` / `partial` |
| `wt2_relevance_flag` | bool | whether this turn was in the WT-2 audit scope |
| `wt3_relevance_flag` | bool | whether WT-3 (type boost scoring) would apply here |
| `wt4_relevance_flag` | bool | whether WT-4 (setter move scoring) would apply here |

### 8. Reward / outcome fields (existing in v1.0, extended)

| field | type | description | status |
|---|---|---|---|
| `terminal_reward` | float | `+1` / `-1` / `0` | existing |
| `discounted_return` | float | discounted return (gamma=0.99) | existing |
| `won` | bool | per-battle | existing |
| `turn_delta_hp` | dict | per-side HP delta this turn | NEW in v1.1 (optional) |
| `faint_caused` | int | count of opp faints this turn | NEW in v1.1 (optional) |
| `faint_suffered` | int | count of our faints this turn | NEW in v1.1 (optional) |
| `positional_advantage` | float | pre-existing measure if any | NEW in v1.1 (optional) |
| `delayed_reward_placeholder` | float | always 0.0 in v1.1 | NEW in v1.1 (required so the field exists for future) |
| `sparse_reward_warning` | bool | `True` if only terminal reward is available | NEW in v1.1 |
| `reward_provenance` | str | always `"terminal_only"` in v1.1 | NEW in v1.1 |
| `reward_confidence` | float | 1.0 for terminal, 0.0 for any dense proxy | NEW in v1.1 |

## Battle-Level Metadata Schema

In addition to per-row fields, each battle must have a
`battle_metadata` block:

| field | type | description |
|---|---|---|
| `battle_id` | str | unique id (matches `episode_id` in rows) |
| `format` | str | `"gen9randomdoublesbattle"` / etc. |
| `team_id` | str | local-only team id |
| `opponent_team_id` | str | local-only opp team id |
| `bot_config_hash` | str | hash of `DoublesDamageAwareConfig` |
| `config_flags` | dict | all config flags as a dict (e.g., `{"enable_protect": true, "enable_anti_trick_room_response": false}`) |
| `random_seed` | int | battle seed (if available) |
| `local_only_provenance` | bool | always `True` |
| `total_turns` | int | total turns in the battle |
| `final_outcome` | str | `"win"` / `"loss"` / `"tie"` |
| `action_distribution` | dict | `{"move": N, "switch": M, "pass": K, "support": S, "protect": P}` — required for fast-fail |
| `support_move_distribution` | dict | per-group action counts (`{"healing_buff_ally_support": N, "weather_terrain": M, ...}`) |
| `weather_terrain_active_turns` | dict | `{"raindance_turns": N, "psychicterrain_turns": M, ...}` |
| `select_random_seed` | int | same as random_seed (kept for clarity) |

This is essentially the existing `v1.0` battle-level fields with
the new **action-distribution** and **support-move-distribution**
counters added for fast-fail. The PROTECT-1 roadmap requires an
action-distribution pre-training audit; this schema formalizes
it.

## Candidate Action Schema

The existing dataset has `v4a_legal_action_keys_slot0/1` and
`legal_joint_action_keys`. v1.1 does **not** change the candidate
representation. The new fields are **derived** from these keys
at build time, not stored as a separate schema.

The classification function (to be added in RL-DATA-2) is:

```python
def classify_action(action_key: str) -> dict:
    """Returns:
    {
        "support_group": str | None,
        "support_status": str | None,
        "safety_only": bool,
        "positive_strategy": bool,
        "opt_in_flag_required": str | None,
        "default_enabled": bool | None,
    }
    """
    # ... see SUPPORT-AUDIT-1 for the groups
```

## Selected Action Schema

Same as v1.0: `selected_joint_key` (V2l.1 key) + `selected_per_slot`
(per-slot action) + `selected_score` (final score) + `selected_rank`
(NEW in v1.1, rank among all candidates).

## Scoring / Heuristic Trace Fields

Same as `Scoring trace` above. The new v1.1 fields
(`damage_estimate`, `protect_stall_score`, `support_bonus`,
`safety_block_score`, `selected_rank`, `score_component_breakdown`)
are optional. They require a future instrumentation phase to
populate. The `v4a_raw_scores_slot0/1` fields exist in v1.0 but
were `None` in BI3M2 (RL-5b root cause). v1.1 will require these
to be populated by the next data collection run.

## Support-Move Instrumentation Fields

See `Support move instrumentation` above. These are the new
v1.1 fields added in response to SUPPORT-AUDIT-1.

## Safety / Block Reason Fields

See `Safety and mechanics fields` above. The new v1.1 fields
(`block_reason_wrong_side`, `block_reason_narrow_ally_heal`,
`block_reason_ability_hard_safety`, `used_species_ability_inference`,
`impossible_target_detected`, `blocked_action_resurrected_by_joint`)
are mandatory assertions. Any row that violates them is
**dataset contamination** and the dataset must be rejected.

## Weather / Terrain Fields

See `Weather / Terrain fields` above. The new v1.1 fields
(`setter_move_legal`, `setter_move_selected`, `type_boost_move_legal`,
`type_boost_move_selected`, `type_boost_applied`,
`weather_terrain_scoring_status`, `wt2_relevance_flag`,
`wt3_relevance_flag`, `wt4_relevance_flag`) require the bot to
record the relevant state at audit time. This is a future
RL-DATA-2 instrumentation phase.

## Ability / Revealed-Only Fields

The v1.0 dataset already preserves `state_snapshot` which includes
the visible (revealed) ability. v1.1 adds:

| field | type | description |
|---|---|---|
| `revealed_ability_source` | str | `"revealed"` / `"singleton_deduction"` / `"unknown"` |
| `used_species_ability_inference` | bool | must be `False` for every row |

The `singleton_deduction` source is allowed only when
`ability_hard_safety_allow_singleton_deduction = True`. The default
is `True` per `AGENTS.md`. Any `species` source is forbidden.

## Reward / Outcome Fields

See `Reward / outcome fields` above. v1.1 keeps terminal reward
as the only allowed reward source. Any dense reward proxy must be
flagged with `sparse_reward_warning = False` and a separate
provenance string. The default in v1.1 is `terminal_only` with
`reward_confidence = 1.0`.

## Data Quality Gates

The following gates must pass before any RL training is allowed
on the dataset. The gates are the v1.0 gates (RL-4) plus the
v1.1 additions. Any failure rejects the dataset.

### v1.0 gates (preserved from RL-4)

1. **Schema conformance**: every row matches `turn_rl_v1.1`
   schema. No missing required fields.
2. **Battle consistency**: every row's `episode_id` matches a
   battle-level metadata block.
3. **Outcome consistency**: `terminal_reward` matches
   `won` / `battle_result`.
4. **Action legality**: `selected_joint_key` is in
   `legal_joint_action_keys`.
5. **No future information**: no row has any field that
   references the post-decision turn.
6. **No leaked hidden info**: no row references unrevealed
   abilities, hidden item info, or species-based inferences.
7. **Local-only provenance**: every row has
   `local_only_provenance = True`.
8. **Random seed recorded**: every battle has a `random_seed`.
9. **Config drift recorded**: every row has `config_hash` and
   the battle's `config_hash` matches.
10. **Action distribution recorded**: every battle has
    `action_distribution` and `support_move_distribution`.

### v1.1 gates (new)

11. **No species-based ability inference**: every row has
    `used_species_ability_inference = False`. Any row with
    `True` rejects the dataset.
12. **No impossible target**: every row has
    `impossible_target_detected = False`. Any row with `True`
    rejects the dataset.
13. **No blocked-action resurrection**: every row has
    `blocked_action_resurrected_by_joint = False`. Any row with
    `True` rejects the dataset.
14. **Support-move distribution not collapsed**: the dataset's
    `support_move_distribution` must include all 9 groups
    (`target_side_safety`, `ability_mechanics_safety`,
    `anti_setup_disruption`, `protection_defensive_support`,
    `speed_turn_control`, `weather_terrain`,
    `healing_buff_ally_support`, `field_side_control`).
    `unknown_needs_probe` is allowed and expected.
15. **Revealed ability only**: every row's
    `revealed_ability_source` is `"revealed"` or
    `"singleton_deduction"`. Any `"species"` rejects the dataset.
16. **Config default invariants**: every row's
    `enable_anti_trick_room_response` is `False`, every row's
    `enable_support_move_target_hard_safety` is `False`, every
    row's `enable_ally_heal_wrong_side_hard_safety` is `False`.
    Any `True` row needs an explicit annotation in
    `support_audit_1_annotation` field.
17. **Action distribution not collapsed into only double
    attacks**: the dataset's overall
    `{"move": ..., "support": ..., "switch": ..., "pass": ...}`
    must have `support >= 5%` and `switch >= 2%` of total
    decisions. This is the PROTECT-1 pre-training audit.
18. **WT-2 / WT-3 / WT-4 coverage**: the dataset's
    `setter_move_legal` and `type_boost_move_legal` counters
    must be present even if zero (counter = 0 is acceptable
    for a heuristic that doesn't use these moves; missing is
    not).

## Leakage / Forbidden Fields

The following fields are **forbidden** in v1.1:

- Any post-decision turn reference (e.g., `next_turn_state`).
- Any unrevealed ability source (`revealed_ability_source = "species"`).
- Any post-decision HP delta beyond `turn_delta_hp` (which is
  per-turn, not post-game).
- Any item information not yet revealed
  (e.g., unrevealed item IDs).
- Any team-preview leak in the row (e.g., the opp's 4 chosen
  Pokémon before the battle starts). Note: `opp_chosen_4` is
  allowed at the BATTLE level (after preview), not at the
  per-turn level.
- Any score derived from `v4a_raw_scores_slot0/1` if those
  fields are `None` for a non-trivial number of rows (e.g.,
  >10% None is a quality warning).
- Any anti-setup bonus score that depends on
  `enable_anti_setup_disruption_intent = True` (anti-setup
  data must be collected with the flag explicitly enabled, and
  rows with the flag enabled must be tagged as such).
- Any `_support_target_block_reason` that contains the
  substring "species" or "Magic Bounce pre-reveal".

## Unknown Support Move Detector

The detector is a function `detect_unknown_support_move(action_key)`
that returns `True` if the action is a support move not present
in the SUPPORT-AUDIT-1 inventory.

The detector is implemented as a hardcoded set of known
support-move ids. The detector is a strict superset of
`support_targets.py` allowlists. Any new support move added
to the game (e.g., new Gen, new move) will be flagged as
`unknown_needs_probe`.

The detector is run at dataset build time. Any row whose
selected action or any candidate action matches an unknown
support move is tagged with `unknown_support_move_detected = True`
and the `support_group` is set to `"unknown_needs_probe"`. The
`action_distribution` summary includes the count of unknown
support moves.

The detector is also run on the action distribution. If the
dataset's `support_move_distribution` includes any
`unknown_needs_probe` rows, the dataset is **flagged for
manual review** before any training run.

## Minimum Dataset Size Targets

Per the v1.0 design (RL-4), the minimum dataset size targets are:

- **Small smoke set**: 20-50 battles, 200-500 turn-level rows.
  Used for unit testing and pipeline validation.
- **5k+ dataset**: at least 5,000 turn-level rows before any
  serious offline learning. The dataset must pass all 18
  quality gates above.
- **Future production dataset**: at least 50,000 turn-level
  rows. Beyond v1.1 scope; deferred until RL-DATA-3.

The current RL-5b dataset is 574 deduped rows. This is the
**small smoke set** baseline. The **5k+ dataset** is the next
target.

## Small Smoke Dataset Plan

1. Reuse the existing `turn_rl_v1.0` dataset (574 deduped rows,
   BI3M2 source).
2. Re-run the existing analyzer on the v1.0 dataset; verify
   all 18 gates pass (10 v1.0 + 8 v1.1). Any v1.1 gate failure
   blocks the v1.0 dataset from being labeled `v1.1`.
3. Run the unknown-support-move detector on the v1.0 dataset.
   Document any `unknown_needs_probe` actions.
4. Re-run the existing RL-7 dry-run on the v1.0 dataset.
   Verify the pipeline still works.
5. Document the v1.0 dataset's `v1.1_gate_status` in
   `turn_rl_v1.0_bi3m2_v1.1_status.md` (a new log file).
6. **No training.** This plan only validates the schema on
   existing data.

## 5k+ Dataset Plan

The 5k+ dataset is the next step after the small smoke set
passes. The plan is:

1. Decide on the data source. Candidate sources:
   - BI3M2 audit re-run with the v1.1 instrumentation
     enabled (this requires the v1.1 instrumentation to be
     added in a future RL-DATA-2 phase).
   - BEHAVIOR-18 source (already has speed-priority fields).
   - A new run of 5,000-10,000 battles on the local
     Showdown server with the v1.1 instrumentation.
2. Predeclare the v1.1 gates. The dataset must pass all 18.
3. Predeclare the action-distribution gate. Per
   PROTECT-1, the action distribution must not be
   double-attack-only.
4. Predeclare the baseline comparisons. The v1.1 dataset
   must include at least three baselines: majority,
   current heuristic, and a simple score-based
   baseline.
5. Predeclare the off-policy evaluation plan. The
   dataset must include at least one counterfactual
   field (e.g., `switch_counterfactual`).
6. **No training.** The 5k+ dataset is for offline
   evaluation only.

## Offline Evaluation Plan

The future offline evaluation must include:

1. **Majority baseline**: predict the most common action per
   state. Compute win rate vs this baseline.
2. **Current heuristic baseline**: predict the
   `selected_joint_key` from the audit. Compute win rate vs
   the same audit's `terminal_reward`.
3. **Simple score-based baseline**: predict the action with
   the highest `v2l1_raw_scores_slot0/1` sum. Compute win
   rate vs this baseline.
4. **Off-policy counterfactual**: for each row, compute the
   win rate if a different action had been selected
   (using `switch_counterfactual` for the voluntary-switch
   case; no general counterfactual is currently available).
5. **Action-distribution analysis**: compute the per-group
   support-move distribution, weather/terrain distribution,
   and switch distribution. Verify the distribution is
   not collapsed.
6. **Sparse-reward warning**: every offline evaluation run
   must print a warning that the reward is terminal-only
   (sparse).

## RL-Readiness Checklist

A future RL training phase is allowed **only** when ALL of
the following are true:

- [ ] `turn_rl_v1.1` schema is defined (this phase).
- [ ] RL-DATA-2 instrumentation phase is complete
  (future).
- [ ] RL-DATA-3 5k+ dataset phase is complete (future).
- [ ] All 18 v1.1 data quality gates pass (10 v1.0 + 8 v1.1).
- [ ] All 3 baselines (majority, current heuristic,
  simple score-based) are evaluated on the 5k+ dataset.
- [ ] The action distribution is not collapsed into
  double attacks.
- [ ] The support-move distribution covers all 9 groups
  (including `unknown_needs_probe`).
- [ ] No row has `used_species_ability_inference = True`.
- [ ] No row has `impossible_target_detected = True`.
- [ ] No row has `blocked_action_resurrected_by_joint = True`.
- [ ] The user has explicitly authorized Phase 7.
- [ ] AGENTS.md has been updated to mark Phase 7 as approved.
- [ ] A "RL training readiness" sign-off note has been
  written and committed.

Until all 13 items are true, RL training is **not approved**.

## Recommended Next Phases

After RL-DATA-1, the following phases are candidates. None are
auto-started.

1. **RL-DATA-2** — add the v1.1 instrumentation to
   `bot_doubles_damage_aware.py` and the audit logger. This
   requires:
   - Adding the new fields to the row schema.
   - Adding the unknown-support-move detector.
   - Adding the per-action support-group classification.
   - Verifying the existing builder and analyzer work with
     v1.1 data.
   - Re-running the audit pipeline to produce v1.1 data.
2. **RL-DATA-3** — 5k+ dataset build (deferred until RL-DATA-2
   is complete).
3. **Phase 7** — actual RL training (deferred; requires user
   authorization per AGENTS.md).

## Constraints Respected

- ✅ No RL training
- ✅ No large dataset collection
- ✅ No battle runs (audit-only; no benchmark)
- ✅ No production behavior change
- ✅ No scoring change
- ✅ No default flip
- ✅ No opt-in flag flipped
- ✅ No Weather/Terrain behavior change
- ✅ No Anti-Trick-Room behavior change
- ✅ No species-based Magic Bounce deduction
- ✅ No new behavior flag added
- ✅ No test changes
- ✅ No `test_51` touch
- ✅ No official Pokémon Showdown servers
- ✅ No commit (per task)
- ✅ No push (per task)
- ✅ Audit / schema planning only

## Status of "TODO" from prior phases

- **RL-8** closeout: `PIPELINE_WORKS / TRAINING_NOT_APPROVED`.
  This phase plans the prerequisites; it does not start training.
- **PROTECT-1** roadmap: action distribution pre-training
  audit. v1.1 dataset schema includes `action_distribution`
  and `support_move_distribution` per the roadmap.
- **SUPPORT-AUDIT-1**: 9 support-move groups classified.
  v1.1 includes `support_group` and `support_status_from_audit`
  for each action.
- **WT-2** setter audit: `SWITCH_SCORING_GAP_CONFIRMED`.
  v1.1 includes `setter_move_legal` / `setter_move_selected`
  / `wt2_relevance_flag` for future instrumentation.

## Files in this plan

- `logs/rl_data_1_turn_level_schema_plan.md` (this file, new)
