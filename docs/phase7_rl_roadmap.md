# Phase 7 Roadmap: From Candidate Scorer to RL

> **Draft** — 2026-06-24. Planning only. No phase is approved for execution
> by default. Each phase requires explicit user authorization before starting.
> RL phases require additional AGENTS.md sign-off.

## 1. Current State

| Property | Value |
|---|---|
| Best offline policy | Phase 7.2E Config G |
| Committed checkpoint | `c4ba86c` |
| Architecture | Flat per-candidate `CandidateScorerMLP` |
| Feature dim | 207 |
| Group accuracy | 54.96% (highest rerun: 56.08%) |
| MRR | 0.6249 |
| Median selected rank | 1 |
| Illegal prediction rate | 0% (structurally enforced — only legal candidates scored) |
| Training objective | Binary cross-entropy (positive-weighted) |
| Training type | Behavior cloning (imitation learning from logged policy) |
| Dataset | ~10,721 turn rows, ~332K candidate rows, ~18K groups |
| Deployment | Offline only, not deployed, not production-integrated |

The current model learns to imitate the bot's past decisions from
turn-level logs. It does not optimize long-term reward. It does not
estimate state value. It does not interact with the environment.

## 2. Lessons Learned So Far

### Candidate scorer was the right move

The per-candidate scorer structurally eliminates illegal predictions
(0% vs 58–60% in the global classifier approach). It beats the global
classifier + legal-mask baseline (54.96% vs 47.7%) and the v2l1 heuristic
(41.08%). This architecture is the correct foundation.

### Flat feature engineering plateaued

Three attempts to add more per-candidate features all caused regression:

| Phase | Features | Baseline | With Features | Delta | Status |
|---|---|---|---|---|---|
| 7.2F | 9 relative v2l1 features (rank, percentile, gap) | 56.08% | 50.42% | -5.66pp | Discarded |
| 7.2G | 5 target-side + 8 action-kind one-hot | 54.99% | 51.15% | -3.84pp | Discarded |
| 7.3A | Listwise softmax CE (same 207-dim features) | 54.96% | 46.82% | -8.14pp | Discarded |

Adding deterministic transforms or classifications of existing features
adds optimization noise without new signal. The 207-dim feature set
(v2l1 + action_id top-200 + action_kind + target scalar + legal_count)
appears sufficient for the current architecture.

### Listwise CE alone was not enough

Changing the loss from per-candidate BCE to group-level softmax CE
(7.3A) did not improve performance. The per-candidate MLP encoder
cannot leverage the group-aware loss without cross-candidate feature
interaction. The model still scores each candidate independently.

### Candidate identity is critical

V4a action keys include Terastallized move variants as separate entries
(`['move', 'tailwind', '0', '']` vs `['move', 'tailwind', '0',
'terastallize']`). Normalizing these to the same key creates 91% of
groups with multiple positive labels. Future group-aware architectures
must handle this at the candidate-key level to avoid training signal
corruption.

## 3. Target Architecture Direction

```
battle state (public info)
     │
     ▼
legal candidate generator (V4a keys from server)
     │
     ▼
candidate encoder (207-dim feature per candidate)
     │
     ▼
group-aware ranker (self-attention over candidate set)
     │
     ▼
policy head (logits over legal candidates)
     │
value head (win probability / expected return)
     │
     ▼
offline RL / PPO warm-start (supervised + RL objective)
     │
     ▼
local self-play RL (environment interaction)
```

Key invariants throughout:
- Action space = legal candidates only (structurally 0% illegal)
- No hidden opponent info
- No species-based ability inference
- Local-only training and execution
- All RL phases require explicit authorization

## 4. Roadmap Overview

| Phase | Title | What | When |
|---|---|---|---|
| **7.2E** | Candidate scorer winner | Current best (committed) | Done |
| **7.2F** | Relative features | Failed, discarded | Done |
| **7.2G** | Target/action features | Failed, discarded | Done |
| **7.3A** | Listwise CE ranker | Failed, discarded | Done |
| **7.3B** | Set/attention ranker | Next candidate | Next |
| **7.4** | Policy + value head | Prepare for RL | After 7.3B |
| **7.5** | Offline RL / PPO | Warm-start RL | After 7.4 |
| **7.6** | Local self-play RL | Full RL training | After 7.5 |

Each phase must pass its acceptance gates before the next can start.
No phase is auto-approved.

## 5. Phase 7.3B — Set/Attention Ranker

**Goal**: Build a better offline policy candidate by adding cross-candidate
interaction via self-attention over the candidate set.

**Architecture**:
- Candidate feature tensor: `[batch, max_candidates, feature_dim]` (207 dim)
- Candidate mask: `[batch, max_candidates]`
- Linear projection: 207 → hidden (128 or 256)
- TransformerEncoder (1–2 layers, 2–4 heads, padding mask)
- Score head: one logit per candidate
- Loss: masked listwise cross-entropy
- Prediction: argmax over valid candidates (structurally 0% illegal)

**Candidate ordering and permutation handling**:
- The candidate set inside a group is conceptually unordered.
- The model must not depend on arbitrary JSON/dataset order unless the
  order is deterministic and documented.
- For the TransformerEncoder prototype, candidate order must be
  deterministic. Recommended initial order:
  1. slot id (slot 0 before slot 1 for same-turn groups, though groups
     are already split by slot — this is a safety preference)
  2. legal candidate index as emitted by the local legal-candidate
     builder (V4a list order from the server)
  3. stable action identity key (for reproducible tie-breaking)
- No learned positional encoding in the first prototype. Candidates are
  treated as a set; attention should rely on candidate features alone.
- Attention mask must handle padding.
- If using DeepSets or Set Transformer in a later iteration, prefer
  permutation-invariant pooling over order-dependent assumptions.
- 7.3B should test whether predictions are stable under harmless
  candidate-order permutations where candidate identity and labels are
  preserved. A permutation-invariance test should be part of the eval
  suite.

**See also**: Candidate Identity and Key Migration (below), which covers
Terastallized variant handling.

**What stays the same**:
- Same 207-dim candidate features (no new flat feature families)
- Same dataset, same battle split
- Same evaluation metrics

**Acceptance gates**:
| Gate | Requirement |
|---|---|
| Tests pass | 107+ new tests, all green |
| Illegal prediction | 0% |
| Group accuracy | >= 54.46% |
| MRR | >= 0.6199 |
| Median selected rank | <= 1 |
| No collapse | top-1 rate < 0.5 |
| **Promotion** (any one): | |
| Group accuracy | > 56.08% |
| Group accuracy > 54.96% and MRR > 0.6249 | both |
| Ally attack | >= 30% |
| Switch regression | <= 16 v2l1-correct missed |

**Output**: offline prototype only. No deployment. No production integration.
Requires a review checkpoint before any commit.

**Risk analysis**:
- Self-attention may overfit on 18K groups → use strong dropout, small model
- Larger memory footprint on RX 6600 8GB → limit batch size, 1–2 layers
- Terastallized variant identity is a new requirement; may need dataset or
  key encoding changes
- See fallback plan below if 7.3B lands between 50% and the minimum gate

### Candidate Identity and Key Migration

7.3A found that V4a/Terastallized move variants can collapse under the
normalized candidate key function (`_candidate_key_from_legal`), creating
91% of groups with multiple positive labels.

**Migration rules**:
- Do **not** silently change `_candidate_key_from_legal` in the committed
  7.2E `CandidateScorerMLP` path. That function is used by both the dataset
  builder and the existing scorer. Changing it retroactively invalidates
  the committed baseline.
- For 7.3B, introduce a separate candidate identity path if needed. The
  identity should include enough fields to distinguish variants:
  - action type (move / switch / pass)
  - move id or switch species
  - target (with sign preserved)
  - candidate index or variant id within the legal list
  - terastallized / V4a variant marker if available
- The 7.3B identity path should be isolated from the 7.2E path. Existing
  7.2E behavior must remain unchanged by default.
- Required tests before any 7.3B training:
  - duplicate legal candidates are detected
  - Terastallized variants do not collapse
  - exactly one positive candidate per valid group
  - multiple-positive groups are blocked or safely deduped with full
    reporting (counts printed, no silent drop)

### Fallback plan if 7.3B lands between 50% and minimum gate

If 7.3B achieves 50–54% group accuracy (below the 54.46% minimum gate
but above the 41% v2l1 heuristic):

- Keep 7.2E Config G as the current best.
- Do not deploy 7.3B.
- Do not use 7.3B as the production policy.
- Analyze whether it improves specific weak categories:
  - ally-targeted attacks
  - switch regression compared to v2l1
  - v2l1-rank-1 / model-rank->3 cases
- If it improves a weak category but loses overall accuracy, classify
  as **useful-but-mixed**.
- Consider using it only as an analysis tool or teacher/ensemble candidate
  in a later explicitly planned phase.
- Do not ensemble automatically without a separate adoption review.

If 7.3B fails below 50%, pause architecture exploration and evaluate
the data-expansion parallel track (see below).

See also: [Evaluation Gates](#10-evaluation-gates-consolidated) for the
consolidated gate table.

## 6. Phase 7.4 — Policy + Value Head

**Goal**: Prepare the policy architecture for RL by adding value estimation
without running RL yet.

**Policy**:
- Use the best offline policy from 7.3B (or 7.2E if 7.3B fails).
- Policy head outputs logits over legal candidates (same as candidate scorer).

**Value head**:
- Predicts win probability (expected return) from the public state.
- Can share the candidate encoder representation where safe.
- Target: terminal win/loss from existing trajectory logs.
- No future leakage — use only pre-decision public state.
- Loss: binary cross-entropy (win/loss) or MSE (return).

**Training**: supervised/offline only. Policy BC loss + value loss jointly.
No PPO. No self-play.

**Metrics**:
- Policy: group accuracy, MRR, median rank (must not regress materially)
- Value: Brier score, log loss, AUC (if both outcome classes present),
  calibration by probability bucket
- Baseline comparison to empirical train-split win-rate prior
- No production integration

**Acceptance gates**:
- Policy does not regress materially vs the base policy
- Value head beats the **empirical train-split win-rate prior**, not a
  naive 50% assumption.
  - Prior reports showed 289 wins / 209 losses in one dataset slice
    (~58% win rate). The dataset win rate varies by split.
  - The value baseline must be computed from the actual training split
    and evaluated on a held-out battle-aware test split.
- No leakage (no post-action fields, no selected_score, no terminal fields)
- Tests pass

See also: [Evaluation Gates](#10-evaluation-gates-consolidated) for the
consolidated gate table.

## 7. Phase 7.5 — Offline RL / PPO Warm-Start

**⚠️ Requires explicit user authorization and AGENTS.md sign-off before execution.**

**Goal**: Introduce RL objective while keeping training offline/local.

**Setup**:
- Policy + value heads initialized from Phase 7.4.
- Advantage estimates from logged trajectories (GAE or similar).
- PPO-style clipped policy objective.
- KL regularization toward the BC warm-start policy.
- Entropy regularization to prevent collapse.
- Legal-candidate action space preserved (no illegal predictions).

**Evaluation**:
- Offline evaluation metrics (no environment interaction yet).
- Compare policy entropy and action distribution to BC baseline.
- Check for policy collapse, mode dropping, or degenerate behavior.
- Local battle simulation if authorized (with explicit scope).

**Acceptance gates**:
| Gate | Requirement |
|---|---|
| Policy entropy | Non-zero (no collapse) |
| Illegal prediction | 0% |
| Group accuracy vs BC | Not massively regressed |
| Action distribution | Not degenerate |
| Tests pass | All |

**Risks**:
- Offline RL can exploit dataset artifacts (distribution shift).
- Reward sparsity — current dataset only has terminal win/loss.
- Delayed/horizon credit assignment is hard with ~18K groups.
- PPO may require careful hyperparameter tuning.

See also: [Evaluation Gates](#10-evaluation-gates-consolidated) for the
consolidated gate table.

## 8. Phase 7.6 — Local Self-Play RL

**⚠️ Requires explicit user authorization + AGENTS.md sign-off + Phase 7.4/7.5 gates.**

**Goal**: Train beyond logged policy by interacting with a local Clone
Showdown environment.

**Setup**:
- Local Showdown server only (`localhost:8000`).
- Controlled opponent pool: baseline bot, latest policy, scripted opponents,
  historical checkpoints.
- No official ladder, no online server.
- PPO/A2C-style actor-critic or self-play league.
- Strict evaluation gates before any parameter update is accepted.

**Safety**:
- Local-only, no official server.
- No deployment without explicit review.
- Hidden-info checks: no species ability inference, no unrevealed moves.
- Anti-cheat: verify the model uses only public pre-decision state.
- Crash/error monitoring: any crash stops the run.
- Battle length monitoring: prevent stall loops.

**Metrics**:
| Metric | Target |
|---|---|
| Win rate vs 7.2E baseline | >= 50% (no regression) |
| Win rate vs SafeRandom | >= 95% |
| Action distribution | Non-degenerate |
| Illegal prediction | 0% |
| Crash/error rate | 0% |
| Anti-cheat | Pass |

## 9. Safety and Scope Rules

(These apply to ALL phases. Unless explicitly authorized.)
- **Local-only**: all training and evaluation uses local datasets and/or
  local `localhost:8000` server.
- **No official server**: never connect to `play.pokemonshowdown.com`.
- **No default flips**: all learned policies remain opt-in until adoption
  gates pass. Current `DoublesDamageAwareConfig` defaults are unchanged.
- **No production integration**: trained models are stored under
  `artifacts/` and not loaded by any production bot path.
- **No species-based ability inference** (AGENTS.md rule).
- **No Magic Bounce species inference**.
- **Anti-TR remains default OFF** unless separately reviewed.
- **Broad support safety remains default OFF** unless separately reviewed.
- **No Wide Guard, Follow Me, or Rage Powder positive scoring changes**
  unless separately reviewed.
- **`test_51` untouched**.
- **No commit of raw model weights or datasets**.
- **No commit/push unless explicit commit checkpoint**.

## 10. Evaluation Gates (Consolidated)

| Phase | Goal | Primary Metric | Minimum | Promotion | Stop Condition |
|---|---|---|---|---|---|
| **7.3B** | Better offline policy | Group accuracy | >= 54.46% | > 56.08% or ally attack >= 30% or switch regression <= 16 | Tests fail or regress below min |
| **7.4** | Add value head | Policy no regress; value Brier | Policy no regress | Value beats win-rate prior | Policy regresses or leakage |
| **7.5** | Offline RL warm-start | Policy entropy > 0; group acc >= BC | No collapse; 0% illegal | Offline eval improves | Collapse, degenerate distribution |
| **7.6** | Local self-play RL | Win rate vs baseline | >= 50% vs 7.2E; 0% crash | > 52% vs 7.2E | Crash, illegal, anti-cheat fail |

## 11. Artifact and Commit Policy

Tracking categories:

| Path | Tracked? | Committed? | Notes |
|---|---|---|---|
| `showdown_ai/` | Yes | Only at review checkpoints | Source/test code |
| `tests/` | Yes | Only at review checkpoints | Test code |
| `docs/` | Yes | After review | Roadmap and design docs |
| `logs/` | No (gitignored) | Never | Local evidence and reports |
| `artifacts/` | No (gitignored) | Never | Model weights, configs, metrics |
| `*.jsonl` (datasets) | No (gitignored) | Never | Raw trajectory data |

Specific rules:
- Code changes are committed only at explicit review checkpoints.
- Model weights, datasets, prediction dumps, and raw trajectories are
  never committed.
- `logs/` is local evidence and remains untracked unless explicitly
  requested.
- `artifacts/` is local output and remains untracked.
- `docs/` is tracked and may be committed after review (as done with this
  roadmap).
- Each phase ends with:
  - A final report (`.md`) in the phase's log directory.
  - `git diff --stat` showing tracked changes.
  - `git status --short` showing tree state.
  - No commit/push unless the phase is a commit checkpoint.

## 12. Parallel Track: Data Expansion

More diverse local-only trajectory data may improve the 7.2E baseline
directly without architecture changes. This is a parallel track to 7.3B,
not a replacement.

**Rules**:
- Data expansion must remain local-only. No official server.
- No long battle collection unless explicitly approved by the user.
- Use latest safe opt-in scoring settings only if explicitly specified.
- Keep 7.2E Config G as the baseline. The expanded dataset must not
  degrade the baseline when the same architecture is retrained.
- Data expansion should have its own phase, acceptance gates, and
  final report.

**Potential future phase name**: `PHASE7_DATA_EXPANSION_PLAN`

**Decisions**:
- Data expansion is not automatic. It requires an explicit plan and user
  approval.
- If 7.3B succeeds, data expansion is lower priority.
- If 7.3B fails below the minimum gate, data expansion should be
  evaluated before a second architecture attempt.

## 13. Open Risks



- **Dataset bias**: the current ~10K rows reflect the current bot policy, not
  optimal play. The model can only imitate what the bot chose.
- **Hidden information**: Showdown Random Doubles has hidden sets. The model
  cannot see opponent items, abilities, or move pools before they are revealed.
  This limits ranking accuracy for switches and coverage moves.
- **Terastallized variant identity**: V4a keys include Terastallized variants
  as independent legal actions but the candidate encoding normalizes them to
  the same key. This creates duplicate-positive groups and corrupts training
  signal. A fix (4-element key or tera flag) must be designed for 7.3B.
- **Group size cap**: max 40 candidates (due to Tera variants). Small
  transformer on ~30-40 tokens per group should fit RX 6600 8GB.
- **Overfitting risk**: ~18K groups is small for a transformer. Strong
  regularization needed.
- **Offline RL distribution shift**: the dataset covers a specific policy's
  actions. Offline RL may assign high value to out-of-distribution actions.
- **Self-play instability**: online RL with neural nets is notoriously
  unstable. Battle outcomes are high-variance (random team generation).
- **Reward sparsity**: only terminal win/loss is available as reward signal.
- **Compute limits**: RX 6600 8GB. No multi-GPU.
- **Evaluation vs reality**: offline metrics may not correlate with actual
  battle win rate.

## 14. Recommended Next Phase

`PHASE7_3B_SET_ATTENTION_RANKER_PLAN_REVIEW`

The roadmap should be reviewed before execution. After review, the
recommended next executable phase is:

`PHASE7_3B_SET_ATTENTION_RANKER_PROTOTYPE`

This implements a cross-candidate self-attention ranker using the existing
207-dim features, with mandatory Terastallized-variant identity handling.
If 7.3B fails to beat 7.2E, pause the group-aware architecture direction
and consider data expansion or alternative approaches.
