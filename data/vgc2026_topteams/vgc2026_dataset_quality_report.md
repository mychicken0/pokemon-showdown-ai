# VGC 2026 Top Teams Dataset Quality Report

Generated: 2026-06-11T17:06:15.514260

## Summary

| Metric | Value |
|--------|-------|
| Total input teams (Pikalytics) | 200 |
| Teams with source URLs | 129 |
| Teams without source URLs (source_missing) | 71 |
| Fetched successfully | 129 |
| Fetch failed | 0 |
| Cache hits | 2 |
| Parsed (complete_ots) | 70 |
| Parsed (partial_ots) | 59 |
| Parse failed | 0 |
| **Battle-ready exported** | **129** |
| **Valid in Showdown (gen9championsvgc2026regma)** | **129** |
| Invalid in Showdown | 0 |
| Success rate | 100.0% |

## By Source Platform

| Platform | Total | With URL | Fetched | Complete | Partial |
|----------|-------|----------|---------|----------|---------|
| limitless | 126 | 126 | 126 | 67 | 59 |
| rk9 | 3 | 3 | 3 | 3 | 0 |
| unknown | 71 | 0 | 0 | 0 | 0 |


## Top Failure Reasons

| Reason | Count |
|--------|-------|
| No source URL from Pikalytics | 71 |


## Validation Details (gen9championsvgc2026regma)

- Valid teams: 129
- Invalid teams: 0
- Invalid species: 0
- Invalid items: 0
- Invalid abilities: 0
- Invalid moves: 0
- Missing Tera types: 129
- Incomplete Pokémon: 0
- Teams with simulation-filled fields (EVs/IVs): 129

## RK9 Scraper Performance

- RK9 HTTP fetch attempts: 3
- RK9 Playwright fallback used: 0
- RK9 success rate: 3/3 (100%)

## Sample Valid Exported Team (Showdown Format)

**Rank 1: ARSAL PURI (2026 Indianapolis Pokémon VGC Regional Championships)**

```
Venusaur @ Focus Sash
Ability: Chlorophyll
Level: 50
EVs: 4 HP
Timid Nature
- Sleep Powder
- Sludge Bomb
- Earth Power
- Protect

Charizard @ Charizardite Y
Ability: Blaze
Level: 50
EVs: 4 HP
Modest Nature
- Heat Wave
- Solar Beam
- Weather Ball
- Protect

Garchomp @ Choice Scarf
Ability: Rough Skin
Level: 50
EVs: 4 HP
Adamant Nature
- Earthquake
- Rock Slide
- Stomping Tantrum
- Dragon Claw

Incineroar @ Sitrus Berry
Ability: Intimidate
Level: 50
EVs: 4 HP
Careful Nature
- Fake Out
- Flare Blitz
- Parting Shot
- Throat Chop

Floetteeternal @ Floettite
Ability: Flower Veil
Level: 50
EVs: 4 HP
Modest Nature
- Moonblast
- Dazzling Gleam
- Calm Mind
- Protect

Sinistcha @ Kasib Berry
Ability: Hospitality
Level: 50
EVs: 4 HP
Relaxed Nature
- Matcha Gotcha
- Rage Powder
- Trick Room
- Protect
```


## Files Generated

- `vgc2026_top200_canonical_ots.json` - Canonical OTS data with source tracking
- `vgc2026_top200_battle_ready.json` - Battle-ready data with simulation defaults marked
- `vgc2026_top200_battle_ready_showdown.txt` - Showdown importable format
- `vgc2026_top200_validation_report.json` - Full validation results
- `vgc2026_top200_fetch_log.csv` - HTTP fetch log
- `vgc2026_top200_incomplete_report.csv` - Incomplete teams report
- `vgc2026_dataset_quality_report.md` - This report
- `vgc2026_failed_sources.csv` - Failed sources detail

## Usage for Phase V2

The battle-ready dataset (`vgc2026_top200_battle_ready.json`) contains all fields needed for poke-env integration:
- Each field has `*_source` metadata indicating: `source_provided`, `simulation_default`, `heuristic`, or `missing`
- All 129 teams validated against local Showdown format `gen9championsvgc2026regma`
- Ready for Monte Carlo / training integration
