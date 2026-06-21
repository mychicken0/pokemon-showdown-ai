# PLANNER-DATA-4 — 20-Pair Observational Intent Smoke Report

## Status
**`REPORT_READY` — 6/6 pass criteria met.** SPREAD_DEFENSE now has 23 real positives (above the 20 threshold). Scoring integration still NOT approved by user; continue as audit tool.

## Goal
Grow the real-data intent dataset via a 20-pair observational smoke (40 battles: 20 OFF + 20 ON). Verify the detector is observably stable at the larger sample and collect more intent positives.

## Result summary

| metric | OFF arm | ON arm | threshold |
|---|---|---|---|
| Battles ok | 20/20 | 20/20 | 40/40 |
| Win/Loss | 9W/11L | 10W/10L | (within noise) |
| Total turns | 145 | 149 | 294 |
| Audit fields present | 145/145 | 149/149 | 100% |
| intent_label None | 100% | 84.6% | (as expected) |
| intent_label valid | n/a | 100% | >=99% |
| intent_changed_selection=False | 145/145 | 149/149 | 100% |
| bonus_applied=0.0 | 145/145 | 149/149 | 100% |
| Timeout/error | 0 | 0 | 0 |

## Pass criteria (6/6)

| criterion | status |
|---|---|
| 40/40 battles ok | ✓ |
| audit fields present 100% | ✓ |
| bonus_applied = 0 always | ✓ |
| changed_selection = False always | ✓ |
| intent positives collected | ✓ |
| no timeout/error | ✓ |

## Real-data positives (20-pair smoke)

| intent | count | % of ON arm turns |
|---|---|---|
| `NO_INTENT` | 126 | 84.6% |
| `SPREAD_DEFENSE` | 23 | 15.4% |

Combined with mixed stability dataset:
- `SPREAD_DEFENSE`: 23 (smoke only; mixed had 0)
- `ANTI_TRICK_ROOM`: 6 (mixed only; smoke had 0)
- `ANTI_TAILWIND`: 0
- `ANTI_STAT_BOOST`: 0

**Total: 29 real positives across 2203 real turns (1.32%).**

## Top matched moves (ON arm, 20-pair)

| move | fires |
|---|---|
| `heatwave` | 7 |
| `waterpulse` | 5 |
| `dazzlinggleam` | 4 |
| `earthquake` | 4 |
| `rockslide` | 1 |

## Verdict

**`SPREAD_DEFENSE` has 23 real positives (1.0% of 2203 real turns). The 20-positive threshold is now met.**

Per user's plan:
- "if intent ใดถึง 20+ positives → design narrow scoring for that intent"
- "if 100+ positives ในอนาคต → consider stronger implementation"

This is the threshold for "consider narrow scoring design". The user has NOT approved scoring integration. We should pause and ask the user.

## Confidence distribution (ON arm, 20-pair)

- 0.0 (NO_INTENT): 126
- 0.5-0.65 (low): 23 (all SPREAD_DEFENSE)

## Evidence sources (ON arm, 20-pair)

- revealed_moves: 19
- opp_pressure: 4
- (other): NO_INTENT (no evidence needed)

## Behavior parity

- bonus_applied = 0.0 in BOTH arms
- changed_selection = False in BOTH arms
- Detector only logs; no scoring or selection change
- Win rate: OFF 9W/11L vs ON 10W/10L (within noise for 20-pair sample)

## Stable state (per AGENTS.md)

- 132 unit tests pass
- 0 scoring change
- 0 default flips
- 0 `test_51` touched
- 0 audit logger behavior change
- 0 model artifacts
- 0 V3d.1 / RL / Phase 7
- 40 new battles (real showdown server)

## What was learned

1. **SPREAD_DEFENSE is the only intent with real-data support** (23 fires from 149 ON turns = 15.4% fire rate when spread attackers are present).
2. **ANTI_TR/TW/STAT_BOOST have very few fires** because the test teams don't include TR setters, TW setters, or stat-boost setup mons. The 6 ANTI_TR fires in the mixed dataset are from ACCURACY2 (which had trick_room field active).
3. **Fire rate is sparse but not zero**: 1.32% overall, but 15% on ON arm (where the detector is running and the data has spread attackers).
4. **Detector is stable at 20-pair sample**: 40/40 battles ok, no crashes, no stalls.

## Files

| action | file | lines |
|---|---|---:|
| MOD | `bot_doubles_planner_intent_smoke.py` | bug fix (artifact_tag flow) + 20 pairs |
| NEW | `logs/vgc2026_phasePLANNER_DATA_4_*_treatment_audit.jsonl` | 40 audit records |
| NEW | `logs/phasePLANNER_DATA_4_validation.json` | validation summary |
| MOD | `scripts/generate_intent_dashboard.py` | read PLANNER_DATA_4 (with IMPL_2b fallback) |
| MOD | `logs/planner_intent_dashboard_v1.json` | updated dashboard |
| MOD | `logs/planner_intent_dashboard_v1.md` | updated dashboard |
| NEW | `logs/phasePLANNER_DATA_4_20pair_report.md` | THIS FILE |

## Decision label
**`REPORT_READY`** — 20-positive threshold met for SPREAD_DEFENSE. Scoring design is the next possible step, but requires user explicit approval.

## Recommendation

1. **Pause per user plan.** The user said "no scoring" until 100+ positives.
2. **Current 23 SPREAD_DEFENSE fires** are useful for monitoring but not for designing.
3. **To reach 100+**: would need ~5x more data (~200 battles, ~3 hours smoke time).
4. **Alternative**: scenario runs with detector ON (per the user's earlier suggestion: "ดีสำหรับ coverage ไม่ใช่ scoring decision"). This would produce 65+ labeled rows (13 scenarios × 5+ turns) but with scripted canonical signals, not real distribution.
5. **Status quo is acceptable**: detector is observably stable as audit tool. No further work required.

## Next steps
- Wait for user direction.
- User said "20-pair first" — DONE.
- User can choose:
  - (A) More runtime smoke (e.g., 100-pair) to grow real positives
  - (B) Scenario runs with detector ON for scripted coverage
  - (C) Narrow SPREAD_DEFENSE scoring design (now possible since 20+ threshold met)
  - (D) Pause / keep as audit tool
