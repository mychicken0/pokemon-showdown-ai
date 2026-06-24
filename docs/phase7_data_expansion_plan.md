# Phase 7 Data Expansion Plan

> **Draft — 2026-06-24.** Plan only. No data collection, no training,
> no source/test code changes, no commit, no push. Future collection
> requires explicit user authorization and a separate approval phase.

## 1. Executive Summary

All Phase 7 architecture and representation branches have been
exhausted on the current dataset. **7.2E CandidateScorerMLP
(group acc 54.96%, MRR 0.6249, illegal 0%, feature dim 207) is
the keeper at `c4ba86c`.** Four architecture changes and two
representation changes failed to beat it; the remaining likely
bottleneck is the dataset.

This plan defines **future local-only data collection tracks** that
could give the existing 7.2E-style candidate scorer more diverse
training signal. It does **not** authorize collection. It does
**not** modify code, tests, or defaults. It does **not** touch
`test_51`.

Five tracks are proposed (A–E), each staged with smoke → pilot →
scale-up. Approval gates and battle-aware evaluation are
predeclared. The recommended next executable phase is
`PHASE7_DATA_EXPANSION_PILOT_COLLECTION_APPROVAL_REQUEST`, not
collection itself.

## 2. Current Keeper

| Property | Value |
|---|---|
| Phase | 7.2E Config G |
| Code baseline | `c4ba86c` |
| Architecture | Flat per-candidate `CandidateScorerMLP` (3-layer MLP) |
| Feature dim | 207 (200 action-ID one-hot + 7 context) |
| Group accuracy | **54.96%** (highest rerun **56.08%**) |
| MRR | **0.6249** |
| Median selected rank | **1** |
| Illegal prediction rate | **0%** (structurally enforced) |
| Deployment | Offline only, not deployed, not production-integrated |

## 3. Closed Architecture and Representation Branches

### Architecture

| Phase | Change | Best Acc | Delta vs 7.2E | Status |
|---|---|---:|---:|---|
| **7.2E** | Flat MLP + BCE | **54.96%** | baseline | **KEEP** |
| 7.2F | + 9 relative v2l1 flat features | 50.42% | -4.54pp | DISCARD |
| 7.2G | + 13 target/action flat features | 51.15% | -3.81pp | DISCARD |
| 7.3A | Listwise softmax CE group ranker | 46.82% | -8.14pp | DISCARD |
| 7.3B | Set/attention Transformer ranker | 47.06% | -7.90pp | DISCARD |

### Representation (current 207-dim)

| Phase | Change | Best Acc | Delta vs 7.2E | Status |
|---|---|---:|---:|---|
| Repr1 emb=16 | learned 16-dim embedding | 54.22% | -0.74pp | DISCARD |
| Repr1 emb=32 | learned 32-dim embedding | 54.12% | -0.84pp | DISCARD |
| Repr2 hybrid emb=16 | 862 vocab + 20 semantic + 7 context | 52.09% | -2.87pp | DISCARD |
| Repr2 hybrid emb=32 | same, dim 32 | 49.93% | -5.03pp | DISCARD |

Representation 2 expanded the action vocab to 862 observed IDs
(+1 unknown bucket) and reduced OOV from 19% to 0%, but the
20-dim semantic features added optimization noise and
underperformed the embedding-only baseline.

**Conclusion**: further architecture or representation changes
on the current dataset are not expected to beat 7.2E. Data
expansion is the next likely lever.

## 4. Existing Dataset Audit

`logs/rl_data_refresh_enhanced_turns.jsonl` (100.5 MB).
Full audit: `logs/phase7_data_expansion_plan/existing_dataset_audit.md`
and `existing_dataset_audit.json`.

| Property | Value |
|---|---|
| Schema | `turn_rl_v1.1` (10,721/10,721 = 100%) |
| Battles | 498 unique |
| Turn rows | 10,721 |
| Candidate rows | 332,486 |
| Avg legal actions / slot | 15.51 (p50=18, p99=28, max=28) |
| Selected-in-legal | 10,721/10,721 (100%) |
| Malformed rows | 0 |
| Local-only provenance | 100% |
| `used_species_ability_inference=True` | 0 |
| `impossible_target_detected=True` | 0 |
| `blocked_action_resurrected_by_joint=True` | 0 |
| Semantic metadata coverage | 69.9% of `pcsc` entries have `metadata_source="order"`; 30.1% are `n/a` |
| Battle outcomes | 5,018 win rows / 5,703 loss rows (per-turn inherits battle result) |
| `live_exploration_enabled` | 0 (this dataset was collected with live exploration OFF) |

### Action distribution (selected, per slot)

| Kind | % |
|---|---:|
| move | 78.6% |
| unknown / pass | 12.6% |
| switch | 8.8% |

Top moves: protect 3,457, tailwind 1,137, knockoff 673,
helpinghand 671, highhorsepower 338, fakeout 305, bodypress 302,
closecombat 277, psychic 274, thunderbolt 271.

Top switches: alomomola 18, spidops 14, reuniclus 13,
palafinhero 13, magcargo 12, gumshoos 12, gardevoir 12,
incineroar 11, eelektross 11, granbull 11. Long tail, many
species appear only once.

### Coverage gaps

1. **Single policy / single seed** — 100% rows come from
   `rl_refresh_enhanced` with one collection run.
2. **No opponent-diversity** — 100% `player_side="bot"`.
3. **Long, shallow switch tail** — top switch species <20 each.
4. **Setup / weather-setter still sparse** even with opt-in
   scoring enabled (0% in pre-opt-in slices; small positive bump
   on tailwind / helping hand with opt-in scoring).
5. **30% of `pcsc` entries have unknown metadata** — `n/a`
   bucket dominates the long tail.
6. **200/862 action-ID one-hot** caps representation coverage;
   662 IDs collapse to all-zero in the current encoding.
7. **No per-battle outcome aggregation** — `won` /
   `battle_result` is duplicated across turns; per-battle
   win rate needs explicit dedup.
8. **Sparse terminal reward only** — `reward_provenance` is
   `terminal_only` for 100% of rows.

## 5. Data Expansion Hypothesis

> **Current model/representation experiments are likely
> overfitting or saturating on the current policy-distribution
> dataset. More diverse local-only trajectories may improve
> the 7.2E-style candidate scorer more than further
> architecture changes.**

**Rules of engagement**:

- 7.2E one-hot remains the baseline to beat.
- Do not replace 7.2E until expanded-data retraining beats
  it on the predeclared acceptance gates.
- Expanded data must be evaluated by **held-out battle-aware
  split** (no random turn-level splits).
- New data must not be mixed blindly without distribution
  checks.
- All training scripts and tests remain on the committed
  7.2E code baseline (`c4ba86c`) until the new data passes
  the acceptance gates.

## 6. Expansion Tracks

### Track A — Baseline scale-up

Same generation settings as the current enhanced data
(`rl_refresh_enhanced`, opt-in WT + SUPPORT-SCORING-1B/1C,
no live exploration). Collect more of the same distribution
to reduce variance.

| Stage | Battles | Purpose |
|---|---:|---|
| A1 | +500 | same-distribution scale-up |
| A2 | +1,000 | confirm A1 trend |
| A3 | +2,000 | saturation check |

**Stop conditions**:

- crash / error rate > 1% of battles
- schema mismatch with `turn_rl_v1.1`
- 7.2E does not improve after A1 + A2 (no signal from
  more-of-the-same)

### Track B — Seed / opponent diversity

Reduce overfitting to one policy distribution. Vary seeds
and opponent policies where the local pipeline supports it
(still strictly local-only).

| Variant | Description |
|---|---|
| B1 | 7.2E-like policy vs `RandomPlayer` (multiple seeds) |
| B2 | 7.2E-like policy vs `SafeRandomPlayer` (multiple seeds) |
| B3 | 7.2E-like policy vs `SimpleHeuristicPlayer` if available locally |
| B4 | 7.2E-like policy self-mirror (D1 vs D2) for paired label balance |

**Rules**:

- no official server
- no online ladder
- no self-play RL
- no deployment
- opponent pools must be local-only and deterministic
  (no LLM, no API, no browser automation)

### Track C — Weak-category targeted data

Improve categories the current model struggles with. Categories
are derived from the audit and the 7.2E error analysis
(`logs/phase7_2e_candidate_scorer_tuning`).

| Target | Goal |
|---|---|
| Ally-targeted attacks (helping hand, pollen puff, etc.) | boost minority recall without diluting other categories |
| Switches | reduce long-tail regression on rare species |
| Support choices (tailwind, screens, hazards) | increase selection rate in legal-but-not-selected cases |
| Setup choices (quiverdance, nasty plot, bulk up, …) | increase selection rate from 0–2% toward ≥5–10% |
| v2l1-rank-1 / model-rank->3 cases | collect more (state, action) pairs where the heuristic is confident but the model downweights |
| Rare action IDs | collect more (state, action) pairs to lift the 200-cap representation |

**Important**:

- Do not artificially leak labels (e.g. do not oversample
  `selected` from a held-out set into the training set
  without marking it as "oversampled").
- Do not break the battle-aware split.
- Targeted data must remain local-only.
- If a category is over-represented relative to its legal
  frequency, that must be logged and reported.

### Track D — Opt-in scoring diversity

Generate data with safe opt-in scoring variants if explicitly
approved. Candidate opt-in settings (all currently default-OFF
in `DoublesDamageAwareConfig`):

| Flag | Purpose |
|---|---|
| `enable_support_positive_scoring` | positive scoring for helpinghand / tailwind |
| `enable_weather_terrain_positive_scoring` (WT-4g) | positive scoring for WT setters |
| `enable_ally_heal_wrong_side_hard_safety` | narrow wrong-side heal safety (default ON) |

**Rules**:

- Do not flip production defaults.
- Every flag combination must be logged in dataset metadata
  (a new optional field, e.g. `opt_in_flag_snapshot`).
- Opt-in collection requires explicit user approval per
  flag combination.
- Keep separate dataset files per flag combination.
- Compare separately before mixing.
- The narrow ally-heal safety is default ON in production
  and is **not** part of the opt-in collection (it is the
  baseline).

### Track E — Representation-supporting data

Collect more examples for rare / unknown action IDs and
semantic categories. Useful regardless of which representation
is eventually chosen.

| Subset | Description |
|---|---|
| E1 | rare move / action coverage (lift tail of selected_move / selected_action_kind) |
| E2 | more switch scenarios (one per active slot 0 / slot 1 combination) |
| E3 | more support / status / setup scenarios |
| E4 | more weather / terrain / field-control contexts (e.g. weather-active starts) |
| E5 | more Tera-variant legal actions to address the 7.3A / 7.3B V4a Terastallized identity issue |

**Rules**:

- local-only
- no official server
- no hidden-info leakage
- do not break `used_species_ability_inference=False` invariant

## 7. Dataset Naming and Schema

### Naming

```
logs/phase7_data_expansion/datasets/
  phase7_data_v1_baseline_scaleup_turns.jsonl       # Track A
  phase7_data_v2_seed_diversity_turns.jsonl         # Track B
  phase7_data_v3_optin_diversity_turns.jsonl         # Track D
  phase7_data_v4_weak_category_turns.jsonl          # Track C
  phase7_data_v5_representation_support_turns.jsonl # Track E
  phase7_data_v6_merged_turns.jsonl                 # post-gate merged dataset
```

The `v1`, `v2`, ... prefix is a cohort name, not a schema
version. Each file follows the current `turn_rl_v1.1` schema
so the existing loader and analyzer work unchanged.

### Schema

The current `turn_rl_v1.1` fields are preserved. New optional
fields allowed without a schema bump:

| Field | Type | Purpose |
|---|---|---|
| `cohort_id` | str | one of `v1_baseline_scaleup`, `v2_seed_diversity`, … |
| `collection_seed` | int | seed used for this battle |
| `opt_in_flag_snapshot` | dict | snapshot of opt-in flag values at collection time |
| `collection_track` | str | `A1`, `A2`, `B3`, `C2`, `D1`, … |

`schema_version` remains `turn_rl_v1.1`. If a future change
requires a new schema version, do not bump the dataset file
silently; bump only after a v1.2 plan review and a separate
loader migration.

### What must not be added as a model feature

Even with new collection, the following are forbidden as
model inputs (already in `_FORBIDDEN_KEYS` for 7.2E):

- `selected_score`, `top_5_alternatives`, `top_5_scores`,
  `final_action_keys`, `score_gap_selected_best_alt`
- `won`, `battle_result`, `terminal_reward`,
  `terminal_win_loss`, `discounted_return`
- `turn_delta_hp`, `faint_caused`, `faint_suffered`
- `live_exploration_*` audit fields (kept for diagnosis, not
  used as features)
- `reward_*` placeholders (still placeholders until Phase 7.4+)
- any future / post-action / outcome / hidden-info field

## 8. Collection Safety Rules

Future data collection must be:

```text
LOCAL ONLY
```

Mandatory:

- local Pokémon Showdown server only (`localhost:8000`)
- never the official Pokémon Showdown server
- no ladder
- no online opponents
- no account usage
- no public server load
- no production deployment
- no default flips
- no RL / self-play training
- no long collection runs unless approved
- stop on crash / error threshold

### Approval

- This plan is **not** approval to collect.
- The future phase
  `PHASE7_DATA_EXPANSION_PILOT_COLLECTION_APPROVAL_REQUEST`
  must ask for explicit approval before running any battles.
- Each cohort (Track A / B / C / D / E) may have its own
  approval request.

## 9. Staged Collection Plan

Each stage below has explicit gates. The plan is **stop on
fail** at every stage.

| Stage | Battles | Goal | Hard gates |
|---|---:|---|---|
| Stage 0 — Smoke | 10 | schema sanity, crash check | localhost:8000 healthy, 0 crashes, 0 schema mismatches, selected-in-legal 100%, `local_only_provenance=True` 100% |
| Stage 1 — Small pilot | 100 | data quality / selected-in-legal / schema check | same as Stage 0 + 0 zero-positive groups, no multi-positive groups, no duplicate battle tags across cohorts (unless intentional) |
| Stage 2 — Baseline scale-up | 500 | first 7.2E retrain comparison | 7.2E one-hot retrained on Train ∪ Stage 2 vs held-out Stage 2 test split must reach `>=54.46%` group acc (min gate) |
| Stage 3 — Medium expansion | 1,000–2,000 | meaningful dataset increase | 7.2E retrained on Train ∪ Stage 3 must reach `>54.96%` group acc on held-out Stage 3 test split (promotion gate) |
| Stage 4 — Large expansion | 5,000+ | only if Stage 3 shows benefit | same as Stage 3 + weak-category recall improvement without overall regression |

Each stage must additionally have:

- explicit max runtime
- crash / error threshold
- schema validation
- selected-in-legal validation
- candidate-count sanity
- no-official-server confirmation
- explicit stop condition

**Hard stop rule**: if a stage fails any of its hard gates,
the next stage does not start. The user must explicitly
re-authorize a redesigned stage.

## 10. Training and Evaluation Plan

After collection is **separately approved and completed**,
retrain the existing 7.2E one-hot on the expanded dataset.

### Primary

```text
7.2E CandidateScorerMLP one-hot baseline on expanded data
```

### Secondary (only after primary)

```text
Representation 1 embedding on expanded data
Representation 2 hybrid semantic on expanded data
```

These are rerun **only if the primary retrain improves** over
the current 7.2E one-hot baseline on the held-out test split.
The committed 7.2E code baseline (`c4ba86c`) is the reference.

### Evaluation

- battle-aware split (no random turn-level splits)
- old-data test set (current `rl_refresh_enhanced`)
- new-data test set (each cohort's held-out battles)
- combined test set (old + new, weighted by battle count)
- distribution shift diagnostics (legal-count distribution,
  selected action distribution, switch tail, semantic
  metadata coverage)
- compare against the committed 7.2E checkpoint at `c4ba86c`
- evaluate weak categories explicitly

### Metrics

| Metric | Purpose |
|---|---|
| Group accuracy | primary promotion metric |
| MRR | ranking quality |
| Median selected rank | degenerate-rank guard |
| Illegal prediction rate | 0% required |
| V2L1 heuristic baseline | 41.13% reference |
| Random legal baseline | 20.50% reference |
| Ally-targeted attack accuracy | weak-category signal |
| Switch accuracy / regression | weak-category signal |
| Support / setup / protect accuracy | weak-category signal |
| v2l1-rank-1 / model-rank->3 count | v2l1 mismatch audit |
| Top prediction concentration | collapse guard |
| Rare action ID accuracy | representation coverage |

### Acceptance gates

| Gate | Requirement |
|---|---|
| Illegal prediction | 0% |
| No leakage | strict |
| Selected-in-legal | 100% (or explained / skipped) |
| Group accuracy | `> 54.96%` on comparable held-out split |
| Promotion | `> 56.08%` OR improves weak categories without overall regression |
| No production integration | strict (no default flip, no bot replacement) |

Weak categories are evaluated by the 7.2E error analysis
metrics in `logs/phase7_2e_candidate_scorer_tuning`. A
"weak-category improvement without overall regression" is
defined as: any one of the weak categories improves by
≥5pp on the held-out split while group accuracy does not
decrease by more than 0.5pp.

## 11. Data Quality Gates

Future collection must pass:

- schema validation (`turn_rl_v1.1` fields present)
- local-only marker (`local_only_provenance=True` 100%)
- selected-in-legal validation (100% or explained / skipped)
- legal candidate count > 0 per row
- no zero-positive candidate groups
- no multi-positive bug (unless intentionally collected and
  marked in the cohort metadata)
- battle-aware split possible (no duplicate battle_tag
  collisions across cohorts, unless intentional and marked)
- no missing required fields beyond known optional metadata
  (e.g. `team_id` is allowed to be `null`)
- no official-server markers (no `play.pokemonshowdown.com`,
  no ladder markers)
- no crash / error spike (Stage 0: 0 crashes; Stage 1: 0
  crashes; Stage 2+: <1% per cohort)
- no malformed JSONL rows
- no target-sign regression
- no feature-leakage fields used (see Section 12)

## 12. Leakage and Safety Rules

The plan must explicitly reject the following as model
features. These are already in `_FORBIDDEN_KEYS` for 7.2E;
this plan reasserts them:

- `selected_action` / `selected_joint` / `selected_joint_key` / `selected_per_slot` (labels)
- `submitted_action` / `final_action_keys` (labels)
- `selected_score` (audit field, forbidden in 7.2B before removal)
- `won`, `battle_result`, `terminal_reward`, `terminal_win_loss`, `discounted_return` (outcomes)
- `turn_delta_hp`, `faint_caused`, `faint_suffered` (post-action)
- `top_5_alternatives`, `top_5_scores`, `score_gap_selected_best_alt` (selection context leakage)
- `live_exploration_*` audit fields (diagnostic only)
- future damage roll result, hit / miss result, secondary effect result
- future switch / faint result
- opponent hidden ability, hidden item, hidden moves
- species-based ability inference (AGENTS.md rule)
- Magic Bounce species inference (AGENTS.md rule)
- official Pokémon Showdown server data
- online ladder data

Also included (not silently changed):

- Anti-TR remains default OFF unless separately approved.
- Broad support target safety remains default OFF unless
  separately approved.
- Wide Guard / Follow Me / Rage Powder scoring is **not**
  added.
- `test_51` is untouched.
- `enable_support_positive_scoring` and
  `enable_weather_terrain_positive_scoring` are opt-in and
  remain default OFF in production (collection may flip
  them per cohort with explicit approval; production is
  unchanged).
- `enable_ally_heal_wrong_side_hard_safety` is default ON
  in production and is the baseline for collection, not an
  opt-in.
- No production default flip without an explicit
  adoption-gate review.

## 13. Approval Requirements

This plan is not approval. The user must explicitly authorize
each of the following before the corresponding work starts:

1. **Pilot collection** — `PHASE7_DATA_EXPANSION_PILOT_COLLECTION_APPROVAL_REQUEST`
   (Stage 0 + Stage 1 only, 10 + 100 battles on `localhost:8000`).
2. **Baseline scale-up** — Stage 2 (500 battles) requires a
   separate approval if Stage 1 passes.
3. **Medium / large expansion** — Stage 3 / Stage 4 require
   separate approvals.
4. **Each opt-in flag combination** for Track D requires its
   own approval.
5. **Any retrain** of 7.2E on expanded data requires its own
   approval and must not run before the cohort is fully
   collected and validated.
6. **Any code change** to `showdown_ai/phase7_1_bc_warmstart_train_local.py`
   or the test file requires its own review checkpoint.

AGENTS.md sign-off is required for any phase that:
- touches `_FORBIDDEN_KEYS`
- introduces new feature families
- changes the production code path (none in this plan)

## 14. Recommended Next Phase

`PHASE7_DATA_EXPANSION_PILOT_COLLECTION_APPROVAL_REQUEST`

This is a **decision-summary** phase, not collection. It
will:
- restate the pilot scope (Stage 0: 10 battles, Stage 1: 100
  battles, both strictly `localhost:8000`)
- list the exact opt-in flag combinations to be used
- declare the stop conditions
- declare the local-only / no-official-server /
  no-RL / no-self-play / no-default-flip / no-`test_51`
  confirmation
- request explicit user approval before any battle runs

Do not collect data in this phase.
