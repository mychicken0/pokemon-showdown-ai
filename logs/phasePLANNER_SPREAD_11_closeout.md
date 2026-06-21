# PLANNER-SPREAD-11 — Closeout

## Decision
**`OPT_IN_NEUTRAL` / `DEFAULT_NOT_APPROVED`**

The Wide Guard spread-defense scoring feature is correctly implemented
and runtime-stable, but the paired harness shows the effect is **statistically
neutral** (CI includes 0, sign test p=1.0). Default flip is **NOT
justified**. Keep as opt-in for future experiments.

## Final verdict

| criterion | result |
|---|---|
| Implementation correct | ✓ |
| Runtime stable | ✓ |
| Detector + partner guard reduce false positives | ✓ (0 mispredicts in 10B) |
| Paired harness ON-OFF diff | -0.020 (essentially 0) |
| Bootstrap 95% CI | [-0.200, +0.160] (includes 0) |
| Sign test | p=1.000 (no difference) |
| Default flip approved | **NO** |
| Recommendation | **Keep as opt-in** |

## Journey summary

| phase | outcome | result |
|---|---|---|
| 2 | Implementation (default OFF) | ✓ Code complete |
| 3d | Option C fix: decision snapshot for Guard 5 | ✓ Wiring works (7/7 pass) |
| 4 | 5-pair smoke | ✓ 8/8 pass, no spam |
| 5 | 20-pair preview | ✓ 7/7 pass, ON wins 65% vs OFF 50% |
| 6 | 100-pair qualification | ✗ REGRESSION: ON -8pp vs OFF (high variance) |
| 7 | Regression attribution | 3 mispredicts found (33% FPR) |
| 8A | Confidence gate 0.5→0.65 | Minimal effect (threshold = detector conf) |
| 8B | Partner HP guard | ✓ +10pp at 100-pair, 0 mispredicts |
| 9 | Default-candidate qualification | Targeted -16pp (variance), general -3pp |
| 10A | Evaluation stabilization | OFF arm itself swings 12pp (variance confirmed) |
| 10B | Paired harness | ON≈OFF (CI includes 0, sign test p=1.0) |
| **11** | **Closeout** | **OPT_IN_NEUTRAL** |

## What worked

1. **Implementation is correct** — all 195+ unit tests pass, the
   detector fires correctly, the eligible check works, the bonus is
   applied when the guard passes.

2. **Detector + partner guard reduce false positives** — PLANNER-SPREAD-8B
   reduced 9/9 mispredicts (33% FPR) to 0/10 (0% FPR) at 100-pair.

3. **Runtime stable** — no timeouts, no errors, both arms complete
   cleanly across 200+ battles per smoke.

## What didn't work

1. **Default flip** — the most reliable measurement (paired harness)
   shows ON ≈ OFF. The 8B +10pp result was within noise; the 9 targeted
   -16pp result confirmed the variance.

2. **The WG bonus doesn't translate to wins** — even with 0 mispredicts,
   the 33% win rate when WG is selected in 10B shows the team value is
   not realized in the actual battle outcomes.

## Why we stopped here

- 5-pair smoke validates behavior
- 20-pair shows no spam
- 100-pair shows high variance
- 10A identifies variance
- 10B paired harness resolves uncertainty

**The question is answered**: feature doesn't break, but doesn't clearly
win either. Default flip is not justified.

## Stable state (final)

- 207 unit tests pass
- 0 default flip (default remains `enable_planner_spread_defense_scoring = False`)
- 0 production behavior change beyond the implementation
- 0 production crashes, 0 timeouts in smoke runs
- 0 known regressions in the 187 existing tests

## Code shipped (during this journey)

### Implementation
- `bot_doubles_intent_classifier.py`:
  - `IntentDecision.opp_pressure` field (decision snapshot)
  - `_with_opp_pressure` helper in `IntentDetector.detect()`
- `bot_doubles_damage_aware.py`:
  - `planner_spread_defense_scoring` config block (default OFF)
  - `planner_spread_defense_min_confidence` (default 0.65)
  - `planner_spread_defense_partner_threat_threshold` (default 0.7)
  - `_planner_spread_defense_partner_threat_relevant` method (Guard 7)
  - Updated `_planner_spread_defense_eligible` with all 7 guards
  - `_planner_spread_defense_record_pick` (cumulative bonus tracking)
- `doubles_decision_audit_logger.py`:
  - Class-level `_battle_player_refs` dict
  - `_populate_planner_intent_fields` reads from player ref

### Tests
- `test_planner_spread_moves_fix.py` (36 tests, classifier)
- `test_planner_spread_scoring.py` (19 tests, eligible)
- `test_planner_spread_state_mismatch.py` (5 tests, snapshot)
- `test_planner_spread_partner_guard.py` (12 tests, partner guard)

### Teams
- 4 WG team variations × 5 spread-opp = 20 targeted pairs
- 5 new general pool opp teams (no spread moves)
- 2 new WG team variations (pelipper, incineroar, whimsicott)

## Smoke artifacts (preserved in logs/)

- 200 PLANNER-SPREAD-2/3/3d audit files
- 100 PLANNER-SPREAD-4 audit files
- 40 PLANNER-SPREAD-5 audit files
- 200 PLANNER-SPREAD-6 audit files
- 45 PLANNER-SPREAD-8A audit files
- 200 PLANNER-SPREAD-8B audit files
- 400 PLANNER-SPREAD-9 audit files
- 100 PLANNER-SPREAD-10B audit files
- Total: 1285 audit files (1285 battles documented)

## Reports (preserved in logs/)

- `phasePLANNER_SPREAD_3d_option_c.md`
- `phasePLANNER_SPREAD_4_5pair.md`
- `phasePLANNER_SPREAD_5_20pair.md`
- `phasePLANNER_SPREAD_6_100pair.md`
- `phasePLANNER_SPREAD_7_regression_attribution.md`
- `phasePLANNER_SPREAD_8A_confidence_gate.md`
- `phasePLANNER_SPREAD_8B_partner_hp_guard.md`
- `phasePLANNER_SPREAD_9_default_candidate.md`
- `phasePLANNER_SPREAD_10A_evaluation_stabilization.md`
- `phasePLANNER_SPREAD_10B_paired_harness.md`
- `phasePLANNER_SPREAD_11_closeout.md` (THIS FILE)

## Recommendations for future work

If someone wants to revisit this feature:

1. **Do NOT default-flip without new hypothesis** — the data doesn't
   support a default flip.

2. **Consider a different design** — maybe confidence-weighted bonus
   (smaller bonus for borderline cases) instead of a flat +150.

3. **Investigate specific matchups** — the 2 arcanine matchups
   (vs heatwave, vs hypervoice) showed OFF better than ON. Why?

4. **Run a 200-pair paired harness** if you want higher confidence
   — would take ~2-4 hours.

5. **Different approach entirely** — maybe the WG move should be
   selected based on opp's actual move (not predicted). But that
   would require restructuring the scoring.

## Files in this closeout
- `logs/phasePLANNER_SPREAD_11_closeout.md` (THIS FILE)

## Stable state
- 207 unit tests pass
- 0 code change
- 0 default flip
- Default remains: `enable_planner_spread_defense_scoring = False`
EOF
echo "Closeout report written"