# PLANNER-IMPL-2c — Closeout / Audit Tool Adoption

## Status
**CLOSED — ADOPTED AS OBSERVATIONAL AUDIT TOOL (default OFF, opt-in for runners/probes)**

The per-turn `IntentDetector` is now an opt-in observational audit tool. It is **NOT** a scoring-integrated planner. Scoring integration is **NOT approved** and requires future data collection + design.

## Decision

| aspect | decision |
|---|---|
| Default state | `enable_planner_intent_detector = False` (per AGENTS.md) |
| Runner/probe opt-in | Yes — runners and probes can enable the flag |
| Production scoring integration | **NOT approved** — deferred until further data + design |
| Default flip | **NO** — flag stays default OFF |
| Audit fields | Stable in `state_snapshot` (7 fields) |
| Fixture tests | 15 pass (PLANNER-IMPL-2) |
| Runtime smoke | 10/10 pass (PLANNER-IMPL-2b) |

## What was delivered

### 1. Per-turn IntentDetector (`bot_doubles_intent_classifier.py`)
- Pure function: `IntentDetector.detect(ctx) -> IntentDecision`
- 4 MVP intents: ANTI_TRICK_ROOM, ANTI_TAILWIND, ANTI_STAT_BOOST, SPREAD_DEFENSE
- 1 default: NO_INTENT
- 5 evidence sources: revealed_moves, field_state, side_condition, opp_counter, opp_pressure
- 4 routes: anti_setup_disruption, spread_defense, none

### 2. Config flag (`DoublesDamageAwareConfig`)
- `enable_planner_intent_detector: bool = False` (default OFF)
- `planner_intent_min_confidence: float = 0.5`
- No new bonus magnitudes (per PLANNER-IMPL-1B constraint)

### 3. choose_move integration (flag-gated, line 7720)
- Default OFF: `self._planner_intent_decision = None` (no detector call, identical path)
- Flag ON: detector runs, attaches decision to self AND `battle._planner_intent_decision`
- No scoring change in either path

### 4. Audit fields (observational only, in `state_snapshot`)
| field | type | default |
|---|---|---|
| `planner_intent_label` | str | None |
| `planner_intent_confidence` | float | None |
| `planner_intent_matched_moves` | list[str] | None |
| `planner_intent_evidence_source` | str | None |
| `planner_intent_routed_to_policy` | str | None |
| `planner_intent_bonus_applied` | float | 0.0 (always, per constraint) |
| `planner_intent_changed_selection` | bool | False (always, per constraint) |

## Verification summary

### Unit tests (PLANNER-IMPL-2)
| suite | tests | result |
|---|---|---|
| `test_bot_vgc2026_scripted_opp` | 17 | ✓ |
| `test_scenario_probe` | 67 | ✓ |
| `test_doubles_intent_classifier` | 33 | ✓ |
| `test_planner_intent_detector` | 15 | ✓ |
| **Total** | **132** | **✓** |

### Runtime smoke (PLANNER-IMPL-2b)
- **10/10 battles ok** (5 OFF + 5 ON)
- OFF arm: 29 turns, all fields None/0/False
- ON arm: 37 turns, all fields valid
- **bonus_applied = 0.0** always (no scoring change)
- **changed_selection = False** always (no behavior change)
- Label distribution: 29 NO_INTENT + 8 SPREAD_DEFENSE (the only intent that fires on real-data spread attackers in the 5-pair sample)

### Key observations
- Real-data intent distribution is sparse: 21.6% SPREAD_DEFENSE, 0% ANTI_TR/TW/STAT_BOOST
- This is consistent with PLANNER-DATA-3 finding: real battles are mostly offensive, not setup
- SPREAD_DEFENSE is the only intent that real data supports for now
- The other 3 MVP intents (ANTI_TR/TW/STAT_BOOST) need more data or different test scenarios

## Stable state (per AGENTS.md)

- 132 unit tests pass
- 0 scoring change
- 0 default flips
- 0 `test_51` touched
- 0 audit logger behavior change
- 0 `learned_preview_v3d1` promotion
- 0 V3d.1 PAUSE resumption
- 0 model artifacts
- 0 new RL/training
- 0 Phase 7
- 5+5 = 10 new battles (real showdown server)

## What is NOT approved

- **Scoring integration** — not approved. The detector only logs intent. No per-slot bonus, no selection modifier, no impact on `_compute_joint_scores`.
- **Per-move policy routing** — not approved. The detector logs `routed_to_policy` (e.g., "anti_setup_disruption") but does NOT trigger the existing per-move policies. The existing policies (`enable_anti_setup_disruption_intent`, `enable_spread_defense_bonus`, `enable_setup_intent_policy`) are independent and controlled by their own flags.
- **Default flip to ON** — not approved. The flag stays default OFF per AGENTS.md.
- **Deferred intents** — not approved. REDIRECTION_RESPONSE, WEATHER_CONTROL, TERRAIN_CONTROL, COMBO_ENABLE are deferred (need target-aware scoring, switch scoring, or combo planner).
- **100/200-pair benchmark** — not approved. The smoke is sufficient for observational validation.

## Next unlock (data-driven)

Before any scoring integration, collect more detector-labeled audits:

1. **More scenario runs**: 13 active scenarios already have scripted canonical signals. Re-run with the detector ON to collect labeled data per family.
2. **Wider bot pool**: collect from existing ACCURACY3 (100-pair) and CONTROL4 (10-pair) audits, plus any future runs.
3. **Track intent distribution over time**: see if SPREAD_DEFENSE / ANTI_* counts grow or stay sparse.
4. **Validate no false positives**: verify detector doesn't fire on irrelevant battles.

## Post-closeout options (3)

### Option 1: Report / dashboard
- Summarize planner intent labels from collected audits
- Plot: intent distribution by family, by arm, over time
- Useful for observability, no scoring change
- Effort: small (analysis script only)

### Option 2: 20-pair observational
- Run a 20-pair observational with the detector ON
- Collect more intent-labeled audits
- Validate stability at slightly larger sample
- Effort: medium (similar to PLANNER-IMPL-2b, larger sample)

### Option 3: Narrow scoring design for SPREAD_DEFENSE
- Only intent with real-data support (8/37 fires in 5-pair smoke)
- Design a minimal per-slot bonus: boost Wide Guard on slot 1 when SPREAD_DEFENSE fires
- Must follow PLANNER-IMPL-1B rules: reuse existing `enable_spread_defense_bonus`, NO new bonus magnitudes
- Requires user explicit approval
- Effort: medium-large (design + smoke + benchmark)

## Recommendation

**Option 1 first** (report/dashboard). It's the smallest step that produces immediate value: summarize the data we already have (101 scenario rows + 2155 mixed rows + 66 real audit turns). This gives a clear picture of intent distribution before any further work.

After Option 1, decide:
- If the distribution looks healthy, **Option 2** (20-pair) to grow the dataset.
- If SPREAD_DEFENSE is the only consistent signal, **Option 3** (narrow scoring design) becomes viable.
- If the distribution is too sparse, **stop and reconsider** — more audits or different test scenarios first.

## File locations (cumulative)

| phase | file | purpose |
|---|---|---|
| PLANNER-DATA-1 | `data/curated_teams/scenarios/SCENARIO_INDEX.md` | 13 active scenarios |
| PLANNER-DATA-1 | `scripts/build_planner_dataset.py` | dataset builder |
| PLANNER-DATA-1 | `logs/planner_dataset_v1.jsonl` | 101 scenario rows |
| PLANNER-DATA-2 | `scripts/run_intent_policy_dryrun.py` | rule-based policy |
| PLANNER-DATA-2 | `logs/planner_intent_dryrun_v1.jsonl` | dry-run annotations |
| PLANNER-DATA-3 | `scripts/run_mixed_stability_test.py` | mixed stability test |
| PLANNER-DATA-3 | `logs/planner_mixed_stability_v1.jsonl` | 2155 mixed rows |
| PLANNER-IMPL-1 | `logs/phasePLANNER_IMPL_1_design.md` | design (only) |
| PLANNER-IMPL-1B | `logs/phasePLANNER_IMPL_1B_bonus_table_hardening.md` | hardened tables |
| PLANNER-IMPL-2 | `bot_doubles_intent_classifier.py` | IntentDetector class |
| PLANNER-IMPL-2 | `test_planner_intent_detector.py` | 15 fixture tests |
| PLANNER-IMPL-2 | `logs/phasePLANNER_IMPL_2_report.md` | implementation report |
| PLANNER-IMPL-2b | `bot_doubles_planner_intent_smoke.py` | smoke runner |
| PLANNER-IMPL-2b | `logs/phasePLANNER_IMPL_2b_smoke_report.md` | smoke report |
| PLANNER-IMPL-2b | `logs/phasePLANNER_IMPL_2b_validation.json` | validation stats |
| PLANNER-IMPL-2b | `logs/vgc2026_phasePLANNER_IMPL_2b_*_treatment_audit.jsonl` | 10 audit records |
| **PLANNER-IMPL-2c** | **`logs/phasePLANNER_IMPL_2c_closeout.md`** | **THIS FILE** |

## Git history (PLANNER phases)

```
47d3277  PLANNER-IMPL-1: design only
5ee7c31  PLANNER-IMPL-2: IntentDetector (observational, default OFF, 15 tests)
5374976  PLANNER-IMPL-2b: 5+5 battle smoke (9/9 pass)
5374976  PLANNER-IMPL-2c: closeout (this commit)
```

## Decision label

**`IMPLEMENTED_OBSERVATIONAL_OPT_IN`** — adopted as audit tool, default OFF, scoring integration NOT approved.
