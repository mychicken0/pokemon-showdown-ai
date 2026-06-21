# PLANNER-DATA-1 — Dataset Summary

**Total rows**: 101
**Scenarios processed**: 13
**Scenarios failed**: 0
**Total battles**: 13

## Rows per scenario

| scenario_id | family | priority | intent | status | rows | battles |
|---|---|---|---|---|---|
| anti_tr_basic | anti_tr | P0 | ANTI_TRICK_ROOM | ok | 7 | 1 |
| anti_tw_basic | anti_tw | P0 | ANTI_TAILWIND | ok | 6 | 1 |
| anti_stat_boost_basic | anti_boost | P0 | ANTI_STAT_BOOST | ok | 5 | 1 |
| spread_def_heat_wave | spread_def | P1 | SPREAD_DEFENSE | ok | 7 | 1 |
| redir_followme_basic | redir | P1 | REDIRECTION_RESPONSE | ok | 5 | 1 |
| spread_def_rock_slide | spread_def | P1 | SPREAD_DEFENSE | ok | 11 | 1 |
| spread_def_earthquake | spread_def | P1 | SPREAD_DEFENSE | ok | 6 | 1 |
| weather_rain_basic | weather | P2 | WEATHER_CONTROL | ok | 8 | 1 |
| beatup_justified_basic | beatup_justified | P2 | COMBO_ENABLE | ok | 14 | 1 |
| terrain_psychic_basic | terrain | P2 | TERRAIN_CONTROL | ok | 4 | 1 |
| terrain_electric_basic | terrain | P2 | TERRAIN_CONTROL | ok | 11 | 1 |
| terrain_grassy_basic | terrain | P2 | TERRAIN_CONTROL | ok | 5 | 1 |
| redir_followme_true_basic | redir | P1 | REDIRECTION_RESPONSE | ok | 12 | 1 |

## Rows by family

- `anti_boost`: 5
- `anti_tr`: 7
- `anti_tw`: 6
- `beatup_justified`: 14
- `redir`: 17
- `spread_def`: 24
- `terrain`: 20
- `weather`: 8

## Rows by intent label

- `ANTI_STAT_BOOST`: 5
- `ANTI_TAILWIND`: 6
- `ANTI_TRICK_ROOM`: 7
- `COMBO_ENABLE`: 14
- `REDIRECTION_RESPONSE`: 17
- `SPREAD_DEFENSE`: 24
- `TERRAIN_CONTROL`: 20
- `WEATHER_CONTROL`: 8

## Intent label mapping (family → intent)

| family | intent |
|---|---|
| `anti_tr` | `ANTI_TRICK_ROOM` |
| `anti_tw` | `ANTI_TAILWIND` |
| `anti_boost` | `ANTI_STAT_BOOST` |
| `spread_def` | `SPREAD_DEFENSE` |
| `redir` | `REDIRECTION_RESPONSE` |
| `weather` | `WEATHER_CONTROL` |
| `beatup_justified` | `COMBO_ENABLE` |
| `terrain` | `TERRAIN_CONTROL` |

## Schema

Each row = 1 turn in a battle. JSON-serializable.

| field | type | description |
|---|---|---|
| `scenario_id` | str | scenario id |
| `family` | str | family (anti_tr, redir, etc.) |
| `priority` | str | P0/P1/P2 |
| `intent_label` | str | ANTI_TRICK_ROOM, etc. |
| `battle_tag` | str | unique battle id |
| `turn` | int | turn number |
| `our_active` | list[str] | bot's active mons |
| `opp_active` | list[str] | opp's active mons |
| `scripted_action_fired` | list | scripted opp's actions this turn |
| `expected_signal` | dict | canonical+gap+passed |
| `state_snapshot` | dict | weather, fields, opp_moves_revealed |
| `bot_legal_responses` | dict | legal moves per slot |
| `bot_selected_action` | dict | parsed selected_joint_order |
| `raw_scores` | dict | raw scores per slot, sorted desc |
| `top_alternatives` | list | top 5 alternatives |
| `candidate_intents` | dict | opp_moves_revealed + scripted actions |
| `outcome` | dict | selected_order, score, legal count |

## Pass criteria

- [x] rows generated for all active scenarios (13/13)
- [x] each scenario has at least 1 scripted action row
- [x] legal response extraction works
- [x] labels match scenario family
- [x] no hidden info leak (only audit-visible fields)
- [x] JSON serializable
