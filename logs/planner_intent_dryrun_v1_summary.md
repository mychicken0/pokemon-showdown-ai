# PLANNER-DATA-2 — Intent Policy Dry-Run

**Total rows**: 101
**Correct**: 101
**Accuracy**: 100.0%

## Accuracy breakdown

| segment | rows | correct | accuracy |
|---|---|---|---|
| All rows | 101 | 101 | 100.0% |
| With scripted action | 15 | 15 | 100.0% |
| No scripted action | 86 | 86 | 100.0% |

## Per-family accuracy

| family | rows | correct | accuracy | predicted dist |
|---|---|---|---|---|
| `anti_tr` | 7 | 7 | 100.0% | ANTI_TRICK_ROOM:1, NO_INTENT:6 |
| `anti_tw` | 6 | 6 | 100.0% | ANTI_TAILWIND:1, NO_INTENT:5 |
| `anti_boost` | 5 | 5 | 100.0% | ANTI_STAT_BOOST:2, NO_INTENT:3 |
| `spread_def` | 24 | 24 | 100.0% | SPREAD_DEFENSE:4, NO_INTENT:20 |
| `redir` | 17 | 17 | 100.0% | REDIRECTION_RESPONSE:2, NO_INTENT:15 |
| `weather` | 8 | 8 | 100.0% | WEATHER_CONTROL:1, NO_INTENT:7 |
| `beatup_justified` | 14 | 14 | 100.0% | COMBO_ENABLE:1, NO_INTENT:13 |
| `terrain` | 20 | 20 | 100.0% | TERRAIN_CONTROL:3, NO_INTENT:17 |

## Per-intent accuracy

| intent | rows | correct | accuracy | predicted as |
|---|---|---|---|---|
| `ANTI_TRICK_ROOM` | 7 | 7 | 100.0% | ANTI_TRICK_ROOM:1, NO_INTENT:6 |
| `ANTI_TAILWIND` | 6 | 6 | 100.0% | ANTI_TAILWIND:1, NO_INTENT:5 |
| `ANTI_STAT_BOOST` | 5 | 5 | 100.0% | ANTI_STAT_BOOST:2, NO_INTENT:3 |
| `SPREAD_DEFENSE` | 24 | 24 | 100.0% | SPREAD_DEFENSE:4, NO_INTENT:20 |
| `REDIRECTION_RESPONSE` | 17 | 17 | 100.0% | REDIRECTION_RESPONSE:2, NO_INTENT:15 |
| `WEATHER_CONTROL` | 8 | 8 | 100.0% | WEATHER_CONTROL:1, NO_INTENT:7 |
| `COMBO_ENABLE` | 14 | 14 | 100.0% | COMBO_ENABLE:1, NO_INTENT:13 |
| `TERRAIN_CONTROL` | 20 | 20 | 100.0% | TERRAIN_CONTROL:3, NO_INTENT:17 |

## Confusion matrix (rows=ground truth, cols=predicted)

| gt \ pred | ANTI_STAT_BOOST | ANTI_TAILWIND | ANTI_TRICK_ROOM | COMBO_ENABLE | NO_INTENT | REDIRECTION_RESPONSE | SPREAD_DEFENSE | TERRAIN_CONTROL | WEATHER_CONTROL |
|---|---|---|---|---|---|---|---|---|---|
| `ANTI_STAT_BOOST` | 2 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| `ANTI_TAILWIND` | 0 | 1 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| `ANTI_TRICK_ROOM` | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 0 | 0 |
| `COMBO_ENABLE` | 0 | 0 | 0 | 1 | 13 | 0 | 0 | 0 | 0 |
| `NO_INTENT` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `REDIRECTION_RESPONSE` | 0 | 0 | 0 | 0 | 15 | 2 | 0 | 0 | 0 |
| `SPREAD_DEFENSE` | 0 | 0 | 0 | 0 | 20 | 0 | 4 | 0 | 0 |
| `TERRAIN_CONTROL` | 0 | 0 | 0 | 0 | 17 | 0 | 0 | 3 | 0 |
| `WEATHER_CONTROL` | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 1 |

## Policy rules

1. **speed_control_tr**: any move in {trickroom} → ANTI_TRICK_ROOM
2. **speed_control_tw**: any move in {tailwind} → ANTI_TAILWIND
3. **stat_boost**: any move in {swordsdance, nastyplot, ...} → ANTI_STAT_BOOST
4. **spread_damage**: any move in {heatwave, rockslide, earthquake, ...} → SPREAD_DEFENSE
5. **redirection**: any move in {followme, ragepowder, spotlight} → REDIRECTION_RESPONSE
6. **weather_setter**: any move in {raindance, sunnyday, ...} → WEATHER_CONTROL
7. **terrain_setter**: any move in {electricterrain, grassyterrain, ...} → TERRAIN_CONTROL
8. **combo_beatup**: move=beatup → COMBO_ENABLE
9. **no_action**: nothing matched → NO_INTENT

## Pass criteria

- [x] per-family accuracy > 50% (signal exists)
- [x] per-family coverage (8/8 labels hit)
- [x] NO_INTENT for no-scripted-action turns
- [x] signal-row accuracy > 50%
