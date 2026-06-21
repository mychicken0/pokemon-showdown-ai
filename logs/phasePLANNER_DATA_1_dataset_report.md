# PLANNER-DATA-1 — Scenario Replay Dataset Report

## Status
**PASS** — dataset built, validated, ready for PLANNER-DATA-2 dry-run.

## Goal
Build a read-only JSONL dataset from existing scenario audit artifacts. No new battles, no scoring change, no training, no default flip.

## Output

| file | description |
|---|---|
| `logs/planner_dataset_v1.jsonl` | 101 rows, 1 per turn |
| `logs/planner_dataset_v1_summary.json` | summary stats |
| `logs/planner_dataset_v1_summary.md` | human-readable summary |
| `scripts/build_planner_dataset.py` | builder (read-only) |

## Dataset shape

- **101 rows** total
- **13 scenarios** processed (13/13 active)
- **0 scenarios failed**
- **13 battles** total (1 per scenario)
- **8/8 intent labels** covered

## Rows per scenario

| scenario_id | family | intent | rows |
|---|---|---|---|
| anti_tr_basic | anti_tr | ANTI_TRICK_ROOM | 7 |
| anti_tw_basic | anti_tw | ANTI_TAILWIND | 6 |
| anti_stat_boost_basic | anti_boost | ANTI_STAT_BOOST | 5 |
| spread_def_heat_wave | spread_def | SPREAD_DEFENSE | 7 |
| spread_def_rock_slide | spread_def | SPREAD_DEFENSE | 11 |
| spread_def_earthquake | spread_def | SPREAD_DEFENSE | 6 |
| redir_followme_basic | redir | REDIRECTION_RESPONSE | 5 |
| redir_followme_true_basic | redir | REDIRECTION_RESPONSE | 12 |
| weather_rain_basic | weather | WEATHER_CONTROL | 8 |
| beatup_justified_basic | beatup_justified | COMBO_ENABLE | 14 |
| terrain_psychic_basic | terrain | TERRAIN_CONTROL | 4 |
| terrain_electric_basic | terrain | TERRAIN_CONTROL | 11 |
| terrain_grassy_basic | terrain | TERRAIN_CONTROL | 5 |

## Intent label coverage

| intent | rows | scenarios |
|---|---|---|
| ANTI_TRICK_ROOM | 7 | 1 (anti_tr_basic) |
| ANTI_TAILWIND | 6 | 1 (anti_tw_basic) |
| ANTI_STAT_BOOST | 5 | 1 (anti_stat_boost_basic) |
| SPREAD_DEFENSE | 24 | 3 (heat_wave, rock_slide, earthquake) |
| REDIRECTION_RESPONSE | 17 | 2 (rage_powder, follow_me) |
| WEATHER_CONTROL | 8 | 1 (rain) |
| COMBO_ENABLE | 14 | 1 (beatup_justified) |
| TERRAIN_CONTROL | 20 | 3 (psychic, electric, grassy) |
| **Total** | **101** | **13** |

## Schema

Each row = 1 turn in a battle, JSON-serializable.

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
| `scripted_action_fired` | list[dict] | scripted opp's actions this turn |
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
- [x] legal response extraction works (78 legal joint orders per turn on average)
- [x] labels match scenario family (1:1 mapping)
- [x] no hidden info leak (only `opp_active` + `opp_active_moves_revealed`, no opp internal/legal/strategy)
- [x] JSON serializable (0 errors over 101 rows)

## Constraints

- **read-only**: no battle runs, no scoring change, no model training
- **no default flip**: existing v3d.1 default is unchanged
- **no v3d.1 promotion**: v3d.1 is still PAUSED
- **no new battles**: built entirely from existing audit artifacts
- **no PL logs**: existing vgc2026_*.jsonl logs are read-only

## Anti-leak audit

Checked for `opp_legal`, `opp_hand`, `opp_full_team`, `opp_revealed`, `opp_strategy`, `opp_internal` patterns. **0 leaks found**.

Dataset only contains:
- `opp_active`: 2-element list of opp's active mons (visible to bot)
- `opp_active_moves_revealed`: 2-element list of opp's revealed moves (visible to bot)
- `scripted_action_fired`: scripted opp's actions (from canonical signal)

All other fields are bot-side: `our_active`, `bot_legal_responses`, `bot_selected_action`, `raw_scores`, `top_alternatives`, etc.

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

## Next: PLANNER-DATA-2

Per the user's plan:
- PLANNER-DATA-2: dry-run intent policy on dataset
- only after dry-run has signal, think about implementation

This is the next step.
