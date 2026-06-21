# PLANNER-DATA-3 — Mixed Dataset Stability Test

**Total rows**: 2155
**Scenario rows**: 101
**Real rows**: 2054

## Scenario dataset (canonical signals)

| segment | rows | correct | accuracy |
|---|---|---|---|
| Total | 101 | 39 | 38.6% |
| With signal | 15 | 15 | 100.0% |
| Without signal | 86 | 24 | 27.9% |

## Real dataset (ACCURACY3 100-pair, 100 battles)

| metric | value | threshold |
|---|---|---|
| Total turns | 2054 | - |
| Fires (non-NO_INTENT) | 436 (21.2%) | - |
| NO_INTENT | 1618 (78.8%) | > 50% |
| Fires with valid trigger | 436 / 436 (100.0%) | 100% |
| Fires without trigger (FPR) | 0 (0.0%) | <= 5% |

## Intent distribution on real fires

| intent | fires | % of real fires |
|---|---|---|
| `WEATHER_CONTROL` | 430 | 98.6% |
| `ANTI_TRICK_ROOM` | 6 | 1.4% |

**Max dominance**: 98.6% (threshold: <= 50%)

## Collision / unknown stats

- Rows with multiple intent signals: 25 (1.2%)
- Rows with intent but no trigger evidence: 0 (0.0%)

## Pass criteria

- [x] scenario signal accuracy >= 95% (got 100.0%)
- [x] real-data FPR <= 5% (got 0.0%)
- [x] all fires have valid trigger evidence (got 436/436)
- [ ] no single intent dominates > 50% of real fires (got 98.6%)
- [x] NO_INTENT is majority on real data (got 78.8%)
