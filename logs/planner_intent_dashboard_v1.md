# PLANNER Intent Audit Dashboard (v1)

**Scope**: read-only summary of all PLANNER artifacts

## Summary

- Scenario dataset rows: **101**
- Dry-run dataset rows: **101**
- Mixed stability rows: **2155**
- Runtime smoke battles: **10** (66 turns)
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

- Glob: `vgc2026_phasePLANNER_IMPL_2b_*_treatment_audit.jsonl`
- Files matched: 10
- Battles: 10
- Turns: 66
- ON arm turns: 37

| intent | count |
|---|---|
| `NO_INTENT` | 29 |
| `ANTI_TRICK_ROOM` | 0 |
| `ANTI_TAILWIND` | 0 |
| `ANTI_STAT_BOOST` | 0 |
| `SPREAD_DEFENSE` | 8 |
| `MISSING` | 29 |

- NO_INTENT ratio: **87.9%**

**Confidence buckets (ON arm)**:

- `0.0 (NO_INTENT)`: 29
- `0.5-0.65 (low)`: 8

**Evidence sources (ON arm)**:

- `MISSING`: 29
- `revealed_moves`: 8

**Top matched moves (ON arm)**:

- `waterpulse`: 5
- `dazzlinggleam`: 3

## Real-data positives (non-NO_INTENT fires)

| intent | mixed_real | smoke_on | combined |
|---|---|---|---|
| `ANTI_TRICK_ROOM` | 6 | 0 | **6** |
| `ANTI_TAILWIND` | 0 | 0 | **0** |
| `ANTI_STAT_BOOST` | 0 | 0 | **0** |
| `SPREAD_DEFENSE` | 0 | 8 | **8** |

## Recommendation

**Top intent**: `SPREAD_DEFENSE` with 8 real positives
**Total real turns audited**: 2091
**Fire rate**: 0.38%

**All intents by real positive count**:

- `SPREAD_DEFENSE`: 8
- `ANTI_TRICK_ROOM`: 6
- `ANTI_TAILWIND`: 0
- `ANTI_STAT_BOOST`: 0

**Verdict**: REPORT_READY: SPREAD_DEFENSE has only 8 real positives (0.4% of 2091 real turns). Keep collecting data; scoring not yet warranted.

## Decision label

`REPORT_READY`
