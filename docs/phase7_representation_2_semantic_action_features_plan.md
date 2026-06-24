# Phase 7 Representation 2: Semantic Action Features Plan

## 1. Executive Summary

The action embedding prototype (Representation 1) did not beat 7.2E. The
embedding preserved ranking fairly well (MRR passed) but did not add new
signal. 19% of action IDs were out-of-vocabulary, mapped to index 0,
losing rare-action identity. The next step is a **hybrid representation**:
learned action embedding + safe semantic action features. The current
dataset provides 70% coverage for `resolved_base_power` and `category` via
`per_candidate_support_classification`, plus target class from V4a,
plus HP fractions and field state from `state_snapshot`. These can provide
**new semantic signal** that the 200-dim one-hot lacked.

## 2. Current Keeper and Failed Attempts

Phase 7.2E CandidateScorerMLP is the keeper at 54.96% group accuracy.
All five architecture changes have been discarded:

| Phase | Change | Best Acc | Delta | Status |
|---|---|---|---|---|
| 7.2E | Flat MLP + BCE | 54.96% | baseline | KEEP |
| 7.2F | + relative v2l1 features | 50.42% | -4.54pp | DISCARD |
| 7.2G | + target/action flat features | 51.15% | -3.81pp | DISCARD |
| 7.3A | Listwise CE ranker | 46.82% | -8.14pp | DISCARD |
| 7.3B | Set/attention ranker | 47.06% | -7.90pp | DISCARD |
| 7-Repr1 | Action embedding (dim 16) | 54.22% | -0.74pp | DISCARD |
| 7-Repr1 | Action embedding (dim 32) | 54.12% | -0.84pp | DISCARD |

## 3. Representation 1 Lessons

* Action embedding alone preserved ranking (MRR 0.6225-0.6226 vs 7.2E 0.6249)
  but did not improve it
* Effective input dim dropped from 207 (one-hot) to 23-39 (embedding) but
  accuracy did not increase
* 19% of action IDs were OOV and mapped to index 0, collapsing rare action
  identity
* The embedding provides no NEW signal over the one-hot because the
  one-hot's 200-dim memorization is already sufficient for 281 unique IDs

## 4. Available Semantic Information Audit

See `logs/phase7_representation_2_semantic_action_features_plan/semantic_feature_audit.md`
for the full audit.

**Key finding**: 70% of candidates have `resolved_base_power` and
`resolved_category` from the live poke-env `Move` object via
`per_candidate_support_classification`. The remaining 30% have
`metadata_source: n/a` and need unknown-bucket handling.

## 5. Safe Feature Candidates (Recommended First Prototype)

### Action type flags (4 dims, always safe)

| Feature | Source | Coverage |
|---|---|---|
| `is_move_action` | psc | 100% |
| `is_switch_action` | psc | 100% |
| `is_pass_action` | psc | 100% |
| `is_protect_like` | psc.action_kind + known protect set | 100% |

### Move metadata (4 dims, 70% coverage)

| Feature | Source | Coverage |
|---|---|---|
| `is_physical` | psc.resolved_category | 70% |
| `is_special` | psc.resolved_category | 70% |
| `is_status` | psc.resolved_category | 70% |
| `base_power_bucket` | psc.resolved_base_power → 7 buckets | 70% |
| `metadata_known` | psc.metadata_source == "order" | 70% |

### Target class (4 dims, 100% coverage)

| Feature | Source |
|---|---|
| `target_is_opponent` | V4a target > 0 |
| `target_is_ally` | V4a target < 0 |
| `target_is_self_or_field` | V4a target == 0 |
| `target_is_switch` | action_kind == "switch" |

### State context (4 dims, 100% coverage)

| Feature | Source |
|---|---|
| `weather_active` | state_snapshot.weather non-empty |
| `field_active` | state_snapshot.fields non-empty |
| `tailwind_active` | "tailwind" in side_conditions |
| `our_hp_low` | min(our_active_hp_fraction) < 0.3 |

**Total first-prototype semantic dims**: ~16

## 6. Excluded Risky/Leaky Features

The plan explicitly rejects:

- `selected_action`, `submitted_action` (labels)
- `selected_score` (directly used in 7.2B before removal)
- `battle_result`, `won`, `terminal_reward` (outcome leakage)
- `turn_delta_hp`, `faint_caused`, `faint_suffered` (post-action)
- `top_5_alternatives`, `top_5_scores` (leak selection context)
- `final_action_keys` (submitted actions)
- Species-based ability inference (AGENTS.md rule)
- Magic Bounce species inference (AGENTS.md rule)
- Opponent hidden ability, item, unrevealed moves
- Future switch/faint result
- Official server data
- Damage roll result, whether move hit, secondary effect result

Also rejected for this phase:
- New damage calculator
- Value head
- RL advantage
- Self-play outcome features
- Online ladder data
- Wide Guard / Follow Me / Rage Powder scoring adoption

## 7. OOV and Rare Action Identity Plan

Representation 1 collapsed 19% of rows to index 0. Improvements:

### Option A — Expanded action vocab (recommended)

Use all observed action IDs (281 in selected) instead of top-200.
Keep unknown bucket for future unseen IDs. Larger embedding table
(281 entries) but still small.

Risk: ~64000 rows (19%) would still map to "unknown" bucket since
the vocab is limited to 281 IDs. But more rows would be resolved.

### Option B — Hash bucket rare actions

Rare actions mapped to several hash buckets. Risk: collisions.

### Option C — Semantic fallback

Unknown action identity is less important if semantic features
describe the action. Embedding unknown + semantic metadata.

**Recommended first prototype**: Option A (expanded vocab to 281 IDs)
+ Option C (semantic fallback for the remaining 19%).

## 8. Recommended Hybrid Representation

```
action_id → expanded vocab (281 IDs, + unknown bucket)
       ↓
learned embedding (dim 16 or 32)
       ↓
concatenate with safe semantic features (~16 dims)
       ↓
concatenate with existing 7 non-ID scalar/context features
       ↓
CandidateScorerMLP
       ↓
score per legal candidate
       ↓
argmax over legal candidates
```

Effective input dim:
- Old: 207 (200 one-hot + 7 context)
- New: 16-32 (embedding) + 16 (semantic) + 7 (context) = 39-55
- vs 207 for one-hot: 3-5x reduction

## 9. Prototype Variant Order

### Variant C — Hybrid + expanded action vocab (recommended first)

Learned action embedding (vocab=281, dim=16 or 32) + 16 safe semantic
features + 7 non-ID context features. Same 7.2E MLP/BCE. Compare against
7.2E one-hot and Representation 1.

### Variant B — Semantic-only ablation

Semantic features + 7 non-ID features, NO action embedding. Test
whether semantic features alone provide signal without action identity.

### Variant D — One-hot + semantic features (diagnostic only)

Keep 200-dim one-hot, add semantic features. Diagnostic to show
whether semantic features help when the one-hot is present.

**Order**: Variant C first → Variant B ablation → optional Variant D.

## 10. Evaluation Gates

### Minimum gates

| Gate | Requirement |
|---|---|
| Tests pass | 107+ new tests |
| No leakage | strict |
| Semantic features verified safe | strict |
| Illegal prediction | 0% |
| Target sign preserved | strict |
| Group accuracy | >= 54.46% |
| MRR | >= 0.6199 |
| Median rank | <= 1 |
| No collapse | top-1 rate < 0.5 |
| Default one-hot path unchanged | strict |

### Promotion gates (any one)

| Gate | Target |
|---|---|
| Group accuracy | > 56.08% |
| Group accuracy > 54.96 and MRR > 0.6249 | both |
| Close to 7.2E but improves weak categories | ally >= 30% or switch regression <= 16 |
| Reduces OOV collapse meaningfully | OOV rows get correct semantic metadata |

## 11. Future Test Requirements

Required future tests:
- Semantic features use only pre-action metadata
- No selected/submitted label as feature
- No result/reward/future/post-action features
- `selected_score` remains forbidden
- Target sign preserved
- Expanded action vocab includes all observed IDs
- Unknown bucket works for OOV
- Semantic missing-value buckets safe
- Status/support markers are metadata only (not scoring adoption)
- No Wide Guard/Follow Me/Rage Powder scoring adoption
- No Magic Bounce species inference
- No species-based ability inference
- Default one-hot path unchanged
- New hybrid representation opt-in only
- Illegal prediction remains 0%
- No production bot integration

## 12. Safety and Scope Rules

- Local-only
- No official server
- No production integration
- No default flips
- No Anti-TR change
- No broad support safety adoption
- No Wide Guard / Follow Me / Rage Powder scoring
- No species-based ability inference
- No Magic Bounce species inference
- `test_51` untouched
- Metadata markers are NOT scoring logic (do not flip scoring)
- All semantic features are pre-action

## 13. Data Expansion Relationship

- This semantic plan does NOT collect new data
- Semantic features tested on current dataset first
- Data expansion remains a separate future track
- If semantic features fail, data expansion may become higher priority
- No long battle collection without explicit approval

## 14. Recommended Next Phase

`PHASE7_REPRESENTATION_2_HYBRID_SEMANTIC_ACTION_FEATURES_PROTOTYPE`

Implement the hybrid representation: expanded action vocab (281 IDs) +
learned embedding (dim 16-32) + ~16 safe semantic features + 7
non-ID context features. Use the same 7.2E MLP/BCE. Keep the one-hot
path as default (unchanged). The new hybrid path is opt-in via
`--candidate-representation hybrid_semantic` (or similar).

Stop condition: if hybrid+semantic doesn't beat 7.2E, pause and
consider data expansion as the next direction.
