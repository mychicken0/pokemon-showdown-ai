# Phase 7 Data Expansion + Representation Learning Plan

## Architecture Branch Closeout

The flat per-candidate CandidateScorerMLP (7.2E) is the keeper. All four
attempts to improve it failed:

| Phase | Change | Best Acc | Delta vs 7.2E | Decision |
|---|---|---|---|---|
| **7.2E** | Flat CandidateScorerMLP + BCE | **54.96%** | baseline | **KEEP** |
| 7.2F | +9 relative v2l1 flat features | 50.42% | -4.54pp | DISCARD |
| 7.2G | +13 target/action flat features | 51.15% | -3.81pp | DISCARD |
| 7.3A | Listwise CE group ranker | 46.82% | -8.14pp | DISCARD |
| 7.3B | Set/attention Transformer ranker | 47.06% | -7.90pp | DISCARD |

Architecture experiments on the current 207-dim representation are stopped.
Further changes must address the representation itself, not the scoring
architecture.

## Current Representation Bottleneck

The representation audit found:

| Feature | Dims | % of Vector | Problem |
|---|---|---|---|
| action_id one-hot | 200 | 96.6% | Sparse memorization; 662/862 vocab IDs map to all-zero |
| action_kind one-hot | 3 | 1.4% | Coarse but ok |
| target/4.0 | 1 | 0.5% | Collapses side/sign info |
| slot | 1 | 0.5% | Constant within group |
| legal_count/30 | 1 | 0.5% | Useful |
| v2l1_score/1000 | 1 | 0.5% | Strong signal |
| **Total** | **207** | **100%** | |

96.6% of the feature vector is a sparse action-ID one-hot where 77% of IDs
are seen ≤5 times. The model memorizes which IDs are "good" rather than
learning why an action is good (its type, power, category, target).

**The key bottleneck is the 200-dim action-ID one-hot representation.**

## Options for Improving Representation

### Option A — Learned Action Embedding (recommended first)

Replace the 200-dim action-ID one-hot with a learned embedding layer.

| Hyperparameter | Candidate Values |
|---|---|
| Embedding dim | 16, 32, or 64 |
| Vocab size | ~862 (all legal action IDs) |
| Unseen/rare ID handling | Zero embedding or `<unk>` index |

**Architecture change** (offline trainer only):
- Input: action_id as integer index
- Embedding layer: `nn.Embedding(vocab_size=862, embedding_dim=16)`
- Concatenate embedding (16) + existing 7 context dims = 23 total dims
- Keep same `CandidateScorerMLP` with adjusted input_dim
- Keep BCE loss, v2l1 feature, same training config

**Expected benefits**:
- Reduces model parameters (~200*256 + bias vs 862*16 + 16*256)
- Generalizes across rare and unseen action IDs
- Frees 193 feature dimensions for future semantic additions
- Simple, low-risk change

**Risks**:
- Rare actions may not train well (mitigation: pre-train embedding on
  legal co-occurrence or use larger dim for rare IDs)
- Seed sensitivity — compare 2 seeds

### Option B — Action Semantic Features

Add pre-action metadata as additional or replacement features.

Available metadata in raw rows:
- `per_candidate_support_classification` dict (action_kind, is_support_move,
  is_move_action, is_switch_action, is_pass_action, resolved_base_power,
  resolved_category)
- V4a legal key (kind, id, target, variant/tera flag)
- `v2l1_raw_scores_slot*` (per-candidate pre-action scores)

Candidate semantic features (safe, pre-action):
- action kind (move/switch/unknown) — already in use
- move category (physical/special/status) — from resolved_category
- base power bucket — from resolved_base_power
- target side (opponent/ally/self/field) — from target sign
- is_tera variant — from V4a 4th element
- is_spread or is_single_target — derivable

**Risk**: 7.2G tried target-side features and regressed. Semantic features
alone likely won't beat the baseline without the embedding change.

### Option C — Hybrid (recommended for later)

Learned action embedding + selected semantic features + current context scalars.

This is the most likely to beat 7.2E, but should be done as:

1. First: Option A alone (measure embedding impact vs 200-dim one-hot)
2. Then: add semantic features on top if embedding helps

### Option D — Data Expansion Only

Collect more local-only trajectories and retrain 7.2E-style model.

Useful as a baseline but doesn't address the representation bottleneck.
More data with the same 200-dim one-hot encoding would likely plateau
at the same ceiling.

## Local-Only Data Expansion Plan

This plan is NOT approved for execution. It defines future options.

| Variant | Description | Battle Count | Purpose |
|---|---|---|---|
| V1 (replay) | Same settings as enhanced data | +500 | Reduce variance |
| V2 (diverse) | Vary seeds, opponent policies | +500 | Broader distribution |
| V3 (opt-in) | Enable safe default-OFF scoring flags | +500 | Action diversity |
| V4 (targeted) | Oversample rare actions, weak categories | +500 | Representation coverage |

**Rules for any future collection**:
- Local Showdown only (`localhost:8000`)
- No official server
- Requires explicit user approval
- Log all config flags
- Battle-aware split preserved
- Schema versioning preserved
- 7.2E remains baseline for comparison

## Safety and Leakage Rules (all phases)

- Legal candidates only — no illegal action space
- No selected_label as feature
- No submitted action as feature
- No future reward/result/post-action fields
- No species-based ability inference
- No Magic Bounce inference
- No official server
- No production integration
- No default flips
- No Anti-TR change
- No broad support safety adoption
- No Wide Guard / Follow Me / Rage Powder scoring
- `test_51` untouched

## Evaluation Gates for Next Phase

| Phase | Main Goal | Primary Metric | Minimum | Promotion | Stop |
|---|---|---|---|---|---|
| **Representation 1** | Action embedding prototype | Group accuracy | >= 54.96% | > 56.08% | Tests fail, acc regresses |
| **Representation 2** | Semantic features (plan only) | — | Plan review | — | Review only |
| **Data Expansion** | Plan + collect (requires approval) | Baseline retrain acc | >= current 7.2E | +1pp over 7.2E | User stop |
| **Policy/Value** | Only after representation improved | Policy acc + value Brier | Policy no regress | Value beats prior | Leakage or collapse |

## Artifact and Commit Policy

- `docs/` may be committed after review
- `logs/` is local/gitignored
- `artifacts/` is local/gitignored
- Model weights, datasets, predictions: NOT committed
- Source/test code changes require separate review checkpoint
- This phase has no commit/push

## Recommended Next Phase

`PHASE7_REPRESENTATION_1_ACTION_EMBEDDING_PROTOTYPE`

Replace the 200-dim action-ID one-hot with a learned embedding (dim 16-32).
Keep all other 7.2E architecture and training unchanged. This is the
smallest change that addresses the identified bottleneck and avoids the
failed flat-feature patterns of 7.2F/7.2G.
