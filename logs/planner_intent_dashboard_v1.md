# PLANNER Intent Audit Dashboard (v1)

**Scope**: read-only summary of all PLANNER artifacts

## Summary

- Scenario dataset rows: **101**
- Dry-run dataset rows: **101**
- Mixed stability rows: **2155**
- Runtime smoke battles: **40** (294 turns)
- All intents observed: `['ANTI_STAT_BOOST', 'ANTI_TAILWIND', 'ANTI_TRICK_ROOM', 'COMBO_ENABLE', 'NO_INTENT', 'REDIRECTION_RESPONSE', 'SPREAD_DEFENSE', 'TERRAIN_CONTROL', 'WEATHER_CONTROL']`

## Per-source distribution

### scenario_dataset

- File: `logs/planner_dataset_v1.jsonl`
- Rows: 101

| intent | count |
|---|---|
| `NO_INTENT` | 0 |
| `ANTI_TRICK_ROOM` | 7 |
| `ANTI_TAILWIND` | 6 |
| `ANTI_STAT_BOOST` | 5 |
| `SPREAD_DEFENSE` | 24 |
| `MISSING` | 0 |

- NO_INTENT ratio: **0.0%**

### dryrun_dataset

- File: `logs/planner_intent_dryrun_v1.jsonl`
- Rows: 101

| intent | count |
|---|---|
| `NO_INTENT` | 0 |
| `ANTI_TRICK_ROOM` | 7 |
| `ANTI_TAILWIND` | 6 |
| `ANTI_STAT_BOOST` | 5 |
| `SPREAD_DEFENSE` | 24 |
| `MISSING` | 0 |

- NO_INTENT ratio: **0.0%**

### mixed_dataset

- File: `logs/planner_mixed_stability_v1.jsonl`
- Rows: 2155

| source | rows | NO_INTENT ratio | intent dist |
|---|---|---|---|
| `scenario` | 101 | 23.8% | NO_INTENT:24, ANTI_TRICK_ROOM:1, ANTI_TAILWIND:1, ANTI_STAT_BOOST:20, SPREAD_DEFENSE:12 |
| `real_acc3` | 1807 | 77.6% | NO_INTENT:1402, ANTI_TRICK_ROOM:1 |
| `real_acc2` | 81 | 61.7% | NO_INTENT:50, ANTI_TRICK_ROOM:5 |
| `real_ctrl` | 166 | 100.0% | NO_INTENT:166 |

### runtime_smoke

- Glob: `vgc2026_phasePLANNER_DATA_4_*_treatment_audit.jsonl`
- Files matched: 40
- Battles: 40
- Turns: 294
- ON arm turns: 149

| intent | count |
|---|---|
| `NO_INTENT` | 126 |
| `ANTI_TRICK_ROOM` | 0 |
| `ANTI_TAILWIND` | 0 |
| `ANTI_STAT_BOOST` | 0 |
| `SPREAD_DEFENSE` | 23 |
| `MISSING` | 145 |

- NO_INTENT ratio: **92.2%**

**Confidence buckets (ON arm)**:

- `0.0 (NO_INTENT)`: 126
- `0.5-0.65 (low)`: 23

**Evidence sources (ON arm)**:

- `MISSING`: 126
- `revealed_moves`: 19
- `opp_pressure`: 4

**Top matched moves (ON arm)**:

- `heatwave`: 7
- `waterpulse`: 5
- `dazzlinggleam`: 4
- `earthquake`: 4
- `rockslide`: 1

## Real-data positives (non-NO_INTENT fires)

| intent | mixed_real | smoke_on | combined |
|---|---|---|---|
| `ANTI_TRICK_ROOM` | 6 | 0 | **6** |
| `ANTI_TAILWIND` | 0 | 0 | **0** |
| `ANTI_STAT_BOOST` | 0 | 0 | **0** |
| `SPREAD_DEFENSE` | 0 | 23 | **23** |

## Recommendation

**Top intent**: `SPREAD_DEFENSE` with 23 real positives
**Total real turns audited**: 2203
**Fire rate**: 1.04%

**All intents by real positive count**:

- `SPREAD_DEFENSE`: 23
- `ANTI_TRICK_ROOM`: 6
- `ANTI_TAILWIND`: 0
- `ANTI_STAT_BOOST`: 0

**Verdict**: REPORT_READY: SPREAD_DEFENSE has 23 real positives (1.0% of 2203 real turns). Sufficient signal to consider narrow scoring design.

## Decision label

`REPORT_READY`
