# PLANNER-REPORT-1 — Intent Audit Dashboard Report

## Status
**`REPORT_READY`** — Dashboard generated, all artifacts read, no crashes, no scoring/default change.

## Goal
Read-only summary of all PLANNER artifacts.

## Result

### Coverage
| source | rows | coverage |
|---|---|---|
| Scenario dataset | 101 | 13 scenarios, 8 intents |
| Dry-run dataset | 101 | same as scenario |
| Mixed stability | 2155 | scenario + real_acc3/acc2/ctrl |
| Runtime smoke | 10 battles / 66 turns | real VGC Champions |

### Intent distribution
- Scenario datasets: 0% NO_INTENT
- Mixed real (acc3): 77.6% NO_INTENT (1 ANTI_TRICK_ROOM from 1807 turns)
- Mixed real (acc2): 61.7% NO_INTENT (5 ANTI_TRICK_ROOM from 81 turns)
- Mixed real (ctrl): 100% NO_INTENT
- Runtime smoke: 87.9% NO_INTENT (8 SPREAD_DEFENSE from 37 ON-arm turns)

### Real-data positives
| intent | mixed_real | smoke_on | combined |
|---|---|---|---|
| SPREAD_DEFENSE | 0 | 8 | 8 |
| ANTI_TRICK_ROOM | 6 | 0 | 6 |
| ANTI_TAILWIND | 0 | 0 | 0 |
| ANTI_STAT_BOOST | 0 | 0 | 0 |

Total: 14 real positives across 2091 real turns (0.67%).

### Top matched moves (ON arm)
- waterpulse: 5 fires
- dazzlinggleam: 3 fires

### Confidence distribution (ON arm)
- 0.0 (NO_INTENT): 29
- 0.5-0.65 (low): 8 (all SPREAD_DEFENSE)

## Verdict

**SPREAD_DEFENSE has only 8 real positives (0.4% of 2091 real turns). ANTI_TRICK_ROOM has 6. Keep collecting data; scoring not yet warranted.**

The threshold of 20 real positives (set in the dashboard) was not met by any intent.

## Recommendation
- Don't pursue scoring integration yet.
- Continue data collection: 20-pair smoke OR scenario runs with detector ON.
- Re-evaluate after 100+ real positives for at least one intent.

## Pass criteria

- [x] reads all available planner-intent artifacts
- [x] outputs markdown + JSON
- [x] no crash on missing fields
- [x] correctly separates scenario rows from real battle rows
- [x] identifies that only SPREAD_DEFENSE has runtime-smoke positives so far
- [x] decision label: REPORT_READY

## Stable state
- 132 unit tests pass
- 0 scoring change
- 0 default flips
- 0 model artifacts
- 0 V3d.1 / RL / Phase 7
- 0 new battle runs (dashboard is read-only)

## Files
| action | file |
|---|---|
| NEW | scripts/generate_intent_dashboard.py |
| NEW | logs/planner_intent_dashboard_v1.json |
| NEW | logs/planner_intent_dashboard_v1.md |
| NEW | logs/phasePLANNER_REPORT_1_dashboard.md (THIS FILE) |

## Decision label
**REPORT_READY**
