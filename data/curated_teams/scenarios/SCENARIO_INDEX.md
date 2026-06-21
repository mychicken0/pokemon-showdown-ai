# Scenario Library Index

> **Source of truth** for all scripted
> scenarios in the library. Updated
> in **SCENARIO-20** (library closeout,
> post-SCENARIO-17/18/19).

## Quick stats

- **Active scenarios**: 9 (3 P0 + 4 P1 + 2 P2)
- **Probes**: 1 (SCENARIO-10A, pre-library)
- **Deferred scenarios**: 4
- **Banned items in VGC 2026**: 5
- **Custom teams**: 4 (`data/curated_teams/custom/`)
- **Custom scenario path**: `data/curated_teams/scenarios/SCENARIO_INDEX.md`
  (this file)

---

## Active scenarios (10)

| # | scenario_id | family | priority | v | opp lead | scripted move | bot response | status | report |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `anti_tr_basic` | anti_tr | P0 | v6 | Hatterene + Blastoise | Trick Room | Taunt (Zoroark-H) | PASS | [report](logs/phaseSCENARIO5_v22_report.md) |
| 2 | `anti_tw_basic` | anti_tw | P0 | v2 | Whimsicott + Kingambit | Tailwind | Taunt (Zoroark-H) | PASS | [report](logs/phaseSCENARIO7_anti_tw_basic_report.md) |
| 3 | `anti_stat_boost_basic` | anti_boost | P0 | v2 | Kingambit + Incineroar | Swords Dance | Taunt (Zoroark-H) | PASS | [report](logs/phaseSCENARIO8_anti_stat_boost_basic_report.md) |
| 4 | `spread_def_heat_wave` | spread_def | P1 | v2 | Volcarona + Blastoise | Heat Wave | Wide Guard (Torterra) | PASS | [report](logs/phaseSCENARIO10_spread_def_heat_wave_report.md) |
| 5 | `redir_followme_basic` | redir | P1 | v2 | Sinistcha + Steelix | **Rage Powder** (not Follow Me) | Heat Wave (Volcarona) | PASS | [report](logs/phaseSCENARIO12_redir_followme_basic_report.md) |
| 6 | `spread_def_rock_slide` | spread_def | P1 | v2 | Tyranitar + Steelix | Rock Slide | Wide Guard (Torterra) | PASS | [report](logs/phaseSCENARIO13_spread_def_rock_slide_report.md) |
| 7 | `spread_def_earthquake` | spread_def | P1 | v2 | Garchomp + Charizard | Earthquake | Wide Guard (Torterra, bot-choice) | PASS | [report](logs/phaseSCENARIO19_spread_def_earthquake_report.md) |
| 8 | `weather_rain_basic` | weather | P2 | v2 | Politoed + Arcanine | Rain Dance | state_snapshot.weather = ['raindance'] | PASS | [report](logs/phaseSCENARIO16_weather_rain_basic_report.md) |
| 9 | `beatup_justified_basic` | beatup_justified | P2 | v2 | Houndoom + Gallade | Beat Up | (Justified ally ready) | PASS | [report](logs/phaseSCENARIO17_beatup_justified_basic_report.md) |
| 10 | `terrain_psychic_basic` | terrain | P2 | v2 | Espathra + Arcanine | Psychic Terrain | state_snapshot.fields = ['psychic_terrain'] | PASS | [report](logs/phaseTERRAIN1_terrain_psychic_basic_report.md) |

### Detailed scenario descriptions

**`anti_tr_basic`** (v6, family 1, P0):
opponent scripts Trick Room (Hatterene
+ Blastoise); bot has Taunt or Encore
legal (Zoroark-H, Whimsicott).

**`anti_tw_basic`** (v2, family 2, P0):
opponent scripts Tailwind (Whimsicott
+ Kingambit); bot has Taunt legal
(Zoroark-H).

**`anti_stat_boost_basic`** (v2,
family 3, P0): opponent scripts Swords
Dance (Kingambit + Incineroar); bot
has Taunt legal (Zoroark-H).

**`spread_def_heat_wave`** (v2, family
4, P1): opponent scripts Heat Wave
(Volcarona + Blastoise); bot has
Wide Guard legal (Torterra).

**`redir_followme_basic`** (v2, family
8, P1): **naming/semantic mismatch —
actual scripted move is Rage Powder,
not Follow Me**. The scenario name
follows the SCENARIO-6 design's
family-level naming (``redir_followme_basic``
covers both Follow Me and Rage
Powder). The basic implementation
starts with Rage Powder (Sinistcha
has it; +4 priority). The Follow Me
variant is deferred. Bot has Heat Wave
legal (Volcarona) as an AoE response.

**`spread_def_rock_slide`** (v2,
family 4, P1): opponent scripts Rock
Slide (Tyranitar + Steelix); bot has
Wide Guard legal (Torterra).

**`spread_def_earthquake`** (v2, family
4, P1): opponent scripts Earthquake
(Garchomp + Charizard). No custom
team needed; uses curated teams.
Earthquake is the only spread move
that doesn't require framework
changes for the basic scenario. The
bot's WG check was removed because
the bot's lead is random and doesn't
always include Torterra.

**`weather_rain_basic`** (v2, family
7, P2): opponent scripts Rain Dance
(Politoed + Arcanine, custom team).
Bot has Tyranitar (Sand Stream) to
counter rain. The validator checks
both the canonical signal (scripted
actions) and the audit signal
(state_snapshot.weather).

**`beatup_justified_basic`** (v2, family
5, P2): opponent scripts Beat Up
(Houndoom + Gallade, custom team).
Gallade (Justified) is the ally ready
to be activated by the bot's Dark-type
move. Custom team was needed because
no curated team has Beat Up.

---

## Probes (1)

| scenario_id | family | purpose | status |
|---|---|---|---|
| `anti_spread_heat_wave_probe` | spread_def | pre-library probe (SCENARIO-10A) for the Heat Wave + Wide Guard legality test. The library entry is `spread_def_heat_wave`. | SUCCEEDED |

The probe uses the old `expected_opp_action_used`
validator (which doesn't work for
scripted scenarios). It was kept for
reproducibility.

---

## Deferred scenarios (4)

| family | proposed scenario_id | reason | blocker type |
|---|---|---|---|
| wp | `wp_super_effective_basic` | Weakness Policy is banned in VGC 2026 Champions format (`isNonstandard: "Past"`). Showdown team validator rejects it. | **format-banned** |
| redir | `redir_followme` (true Follow Me variant) | Rage Powder covers basic redirection. Follow Me is +0 priority, may be outsped. Different script from Rage Powder. | not started |
| terrain_electric_basic` / `terrain_grassy_basic` | Psychic Terrain variant done (TERRAIN-1). Electric/Grassy variants can use custom team with the corresponding setter. | not started |
| — | Earthquake framework-level changes (grounded / Levitate / Flying detection) | Not needed for basic EQ scenario (SCENARIO-19). Only required for "is the move effective" checks. | deferred |

---

## Banned items in VGC 2026 Champions

The following items are marked
`isNonstandard: "Past"` in
`data/mods/champions/items.ts` and
are **rejected by the showdown team
validator**:

| item | effect | banned? |
|---|---|---|
| **Weakness Policy** | +2 Atk/+2 SpA on super-effective hit | ✗ PAST |
| **Absorb Bulb** | +1 SpA on Water-type hit | ✗ PAST |
| **Cell Battery** | +1 Atk on Electric-type hit | ✗ PAST |
| **Eject Button** | forces opponent to switch when hit | ✗ PAST |
| **Eject Pack** | switch out when stat dropped | ✗ PAST |

These items were banned in VGC 2026
as part of the "no free stat boosts"
design philosophy. The showdown server
explicitly rejects them with errors
like:

```
- Dragonite's item Weakness Policy does not exist in Gen 9.
- Baxcalibur's item Loaded Dice does not exist in Gen 9.
```

(Loaded Dice is a different item; it's
also banned for some Pokémon.)

**Implication**: SCENARIO-18 (Weakness
Policy) cannot be tested in VGC 2026
Champions. Same for any "boost on hit"
item scenarios. This is a format
limitation, not a code limitation.

---

## Custom teams (3)

All custom teams are in
`data/curated_teams/custom/`.

### `weather_demo_v1.json` (used by SCENARIO-16)

- **Politoed** (Drizzle, Leftovers) — Rain Dance carrier
- **Arcanine** (Intimidate, Sitrus Berry) — Protect partner
- **Kingambit** (Defiant, Shuca Berry)
- **Garchomp** (Rough Skin, Yache Berry)
- **Tyranitar** (Sand Stream, Choice Scarf)
- **Volcarona** (Flame Body, Lum Berry)

### `beatup_justified_demo_v1.json` (used by SCENARIO-17)

- **Houndoom** (Flash Fire, Sitrus Berry) — Beat Up carrier
- **Gallade** (Justified, Shuca Berry) — Justified ally
- **Arcanine** (Intimidate, Lum Berry)
- **Kingambit** (Defiant, Leftovers)
- **Garchomp** (Rough Skin, Yache Berry)
- **Tyranitar** (Sand Stream, Choice Scarf)

### `terrain_demo_v1.json` (used by TERRAIN-1)

- **Espathra** (Opportunist, Leftovers, Modest, Psychic Terrain / Psychic / Roost / Protect) — the Psychic Terrain setter
- **Arcanine** (Intimidate, Sitrus Berry, Jolly, Protect / Extreme Speed / Flare Blitz / Crunch) — the Protect partner
- **Kingambit** (Defiant, Shuca Berry, Adamant, Kowtow Cleave / Sucker Punch / Iron Head / Protect)
- **Garchomp** (Rough Skin, Yache Berry, Jolly, Earthquake / Rock Slide / Protect / Scale Shot)
- **Tyranitar** (Sand Stream, Choice Scarf, Adamant, Rock Slide / Crunch / Dragon Dance / Protect)
- **Volcarona** (Flame Body, Lum Berry, Timid, Heat Wave / Quiver Dance / Protect / Bug Buzz)

### `wp_demo_v1.json` (used by SCENARIO-18, DEFERRED)

- **Dragonite** (Multiscale, Weakness Policy) — WP holder (item banned)
- **Baxcalibur** (Thermal Exchange, Loaded Dice) — Ice attacker (also banned)
- **Arcanine** (Intimidate, Lum Berry)
- **Kingambit** (Defiant, Leftovers)
- **Garchomp** (Rough Skin, Yache Berry)
- **Tyranitar** (Sand Stream, Lum Berry)

This team was created but cannot be
used in VGC 2026 Champions (both
Weakness Policy and Baxcalibur/Loaded
Dice are banned).

---

## Framework policy (Option C)

### Canonical signal

The validator uses the **baseline
audit's** ``scripted_actions`` field
as the **canonical signal**. The
**treatment audit's**
``opponent_actions.opponent_used_X``
field is a **diagnostic cross-check**
only.

Pass condition: the canonical signal
must have the scripted action with
``executed=True``. Cross-check
disagreement does NOT fail the
scenario; it sets
``bot_opp_action_gap=True`` for
observability.

This policy is implemented in the
``expected_scripted_action`` validator
type (added in SCENARIO-11b).

### Why Option C

The treatment audit's
``opponent_actions`` field is empty
(or ``None``) for scripted scenarios
because the audit logger's
``update_previous_turn`` does not
parse the scripted opp's protocol
events into the bot's
``opponent_actions`` (the scripted
opp's protocol events are processed
by the scripted player's own audit,
not the bot's).

The baseline audit's
``scripted_actions`` IS the canonical
record of what the scripted player
did. It is populated by
``ScriptedOpponentPlayer`` and is
always reliable.

### Expected cross-check pattern

| canonical | treatment `opponent_used_X` | `bot_opp_action_gap` | `passed` |
|---|---|---|---|
| fired (True) | True | False | ✓ |
| fired (True) | False or None | True | ✓ |
| fired (True) | not present | True | ✓ |
| not fired (False) | True | — | ✗ (canonical hard fail) |
| not fired (False) | False or None | — | ✓ (expected) |

**All 9 active scenarios currently
show**: canonical=True, treatment
`opponent_used_X`=None, gap=True.
This is the **expected pattern** for
scripted scenarios.

---

## Validator types

| type | description | preferred for |
|---|---|---|
| `expected_scripted_action` | Option C canonical signal check. Reads baseline `scripted_actions`; cross-checks treatment `opponent_actions`. Sets `bot_opp_action_gap`. | **scripted scenarios** |
| `expected_opp_action_used` | Legacy: reads treatment `opponent_actions.opponent_used_X` only. Does not work for scripted scenarios. | backward compat only |
| `expected_audit_signal` | Reads `state_snapshot.X` from the audit. | cross-check (e.g., weather) |
| `expected_bot_legal_response` | Reads the bot's `v2l1_legal_action_keys_slotN`. | bot response check |
| `no_script_failures` | Skeleton: always passes. | diagnostic |

The **probe scenario** (`anti_spread_heat_wave_probe.json`)
still uses the old `expected_opp_action_used`
validator. The library scenarios all
use the new `expected_scripted_action`
validator.

---

## Usage

### Run a scenario

```bash
timeout --foreground --signal=TERM --kill-after=10s 250s \
  ./venv/bin/python bot_vgc2026_phaseV3a2_reality.py \
    --tag <tag> --n-pairs 1 --start-pair 0 \
    --our-team-file <our_team> \
    --opp-team-file <opp_team> \
    --scenario-file <scenario_file> \
    --audit-decisions \
    --overwrite
```

### Validate a scenario (with Option C)

```python
from scenario_probe import (
    load_scenario_file,
    run_validators_with_canonical,
)
import json

sc = load_scenario_file(
    "data/curated_teams/scenarios/<scenario>.json"
)
with open("logs/vgc2026_<tag>_baseline_audit.jsonl") as f:
    baseline = [json.loads(line) for line in f]
with open("logs/vgc2026_<tag>_treatment_audit.jsonl") as f:
    treatment = [json.loads(line) for line in f]

results = run_validators_with_canonical(
    sc, baseline, treatment
)
for r in results:
    v = r["validator"]
    print(
        f"{'✓' if r['passed'] else '✗'} {v.name} "
        f"({v.type})"
    )
    if v.type == "expected_scripted_action":
        print(
            f"    canonical={r.get('canonical_signal_fired')} "
            f"xcheck={r.get('bot_opp_action_crosscheck')} "
            f"gap={r.get('bot_opp_action_gap')}"
        )
```

### Run all 84 unit tests

```bash
./venv/bin/python -W error::ResourceWarning -m unittest \
    test_bot_vgc2026_scripted_opp test_scenario_probe
```

---

## Family coverage

| family | scenarios | priority | notes |
|---|---|---|---|
| `anti_tr` | `anti_tr_basic` | P0 | ✓ DONE |
| `anti_tw` | `anti_tw_basic` | P0 | ✓ DONE |
| `anti_boost` | `anti_stat_boost_basic` | P0 | ✓ DONE |
| `spread_def` | `spread_def_heat_wave`, `..._rock_slide`, `..._earthquake` | P1 | ✓ 3 variants |
| `redir` | `redir_followme_basic` (Rage Powder), Follow Me variant | P1 | partial (1/2) |
| `weather` | `weather_rain_basic` | P2 | ✓ 1 variant (custom team) |
| `beatup_justified` | `beatup_justified_basic` | P2 | ✓ 1 variant (custom team) |
| `wp` | (DEFERRED — Weakness Policy banned) | P2 | format-banned |
| `terrain` | (DEFERRED — no terrain setters) | P2 | needs custom team |
| `ally_activation` | (covered by beatup_justified) | — | ✓ |

**Coverage by priority**:
- P0: 3/3 families ✓
- P1: 2/2 families ✓ (spread_def 3 variants, redir 1 variant)
- P2: 2/4 families ✓ (weather, beatup_justified); 2 deferred (wp, terrain)

---

## Anti-leak policy

- ✅ Scenarios use scripted opponent
  (inherits from base ``Player``)
- ✅ No scoring change in
  ``bot_doubles_damage_aware.py``
- ✅ No default flip
- ✅ No ``test_51`` touched
- ✅ No ``learned_preview_v3d1``
  promotion
- ✅ No V3d.1 PAUSE resumption
- ✅ No Wide Guard / Taunt / Encore
  scoring added
- ✅ No planner scoring touched

---

## Scenario file format

```json
{
  "scenario_id": "<unique_id>",
  "description": "<one-line description>",
  "version": 1,
  "our_team_file": "data/curated_teams/<family>/<team>.json",
  "opp_team_file": "data/curated_teams/<family>/<team>.json",
  "lead": {
    "opp_slot_0": "<species>",
    "opp_slot_1": "<species>"
  },
  "script": {
    "turn_1": {
      "opp_slot_0": {"move": "<move_id>"},
      "opp_slot_1": {"move": "<move_id>"}
    }
  },
  "validators": [
    {
      "name": "<validator_name>",
      "type": "expected_scripted_action",
      "expected": true,
      "field": "<move_id>"
    },
    {
      "name": "bot_legal_<move>",
      "type": "expected_bot_legal_response",
      "expected": "<Move Name>"
    },
    {
      "name": "no_script_failures",
      "type": "no_script_failures"
    }
  ]
}
```

### Move ID normalization

Move IDs in the ``script`` and
``field`` are normalized by
``_normalize_move_id``: lowercase,
strip whitespace, dashes,
underscores, apostrophes. Examples:

- ``"Trick Room"`` → ``"trickroom"``
- ``"Swords_Dance"`` → ``"swordsdance"``
- ``"Heat Wave"`` → ``"heatwave"``

---

## File map

```
data/curated_teams/
├── control4a/                              # curated teams (control4a batch)
│   ├── team_006.json
│   ├── team_020.json
│   ├── team_027.json
│   ├── team_046.json
│   └── team_057.json
├── item2/                                  # curated teams (item2 batch)
│   ├── team_000.json
│   ├── team_001.json
│   ├── team_010.json
│   ├── team_027.json
│   └── team_029.json
├── custom/                                 # custom teams (for P2 scenarios)
│   ├── weather_demo_v1.json
│   ├── beatup_justified_demo_v1.json
│   └── wp_demo_v1.json (DEFERRED)
└── scenarios/                              # scenario library
    ├── SCENARIO_INDEX.md                    # this file
    ├── anti_tr_basic.json
    ├── anti_tw_basic.json
    ├── anti_stat_boost_basic.json
    ├── spread_def_heat_wave.json
    ├── redir_followme_basic.json
    ├── spread_def_rock_slide.json
    ├── spread_def_earthquake.json
    ├── weather_rain_basic.json
    ├── beatup_justified_basic.json
    ├── wp_super_effective_basic.json (DEFERRED)
    └── anti_spread_heat_wave_probe.json (probe)

logs/
├── phaseSCENARIO5_v22_report.md             # P0 family 1
├── phaseSCENARIO7_anti_tw_basic_report.md   # P0 family 2
├── phaseSCENARIO8_anti_stat_boost_basic_report.md  # P0 family 3
├── phaseSCENARIO9_p0_framework_closeout_report.md  # P0 closeout
├── phaseSCENARIO10A_p1_spread_heat_wave_probe_report.md  # P1 probe
├── phaseSCENARIO10_spread_def_heat_wave_report.md  # P1 family 4
├── phaseSCENARIO11_p1_review_spread_signal_gap_report.md  # P1 review
├── phaseSCENARIO11b_option_c_validator_report.md  # Option C validator
├── phaseSCENARIO12_redir_followme_basic_report.md  # P1 family 8
├── phaseSCENARIO13_spread_def_rock_slide_report.md  # P1 family 4 variant
├── phaseSCENARIO14_earthquake_deferred_report.md  # P1 family 4 deferred (now superseded by SCENARIO-19)
├── phaseSCENARIO15_p1_closeout.md            # P1 closeout
├── phaseSCENARIO16_weather_rain_basic_report.md  # P2 family 7
├── phaseSCENARIO17_beatup_justified_basic_report.md  # P2 family 5
├── phaseSCENARIO18_wp_super_effective_deferred_report.md  # P2 family 6 deferred
├── phaseSCENARIO19_spread_def_earthquake_report.md  # P1 family 4 (Earthquake done)
└── phaseSCENARIO20_library_closeout.md     # library closeout (this phase)
```

---

## Version history

- v1 (SCENARIO-2/3): initial scenario
  framework
- v2 (SCENARIO-4): lead config added
- v3 (SCENARIO-5): pipeline integration
- v4 (SCENARIO-5): scenario_id stable,
  probe support
- v5 (SCENARIO-8): Hatterene+Blastoise
  lead restored (post-/team format
  fix)
- v6 (SCENARIO-11b): Option C canonical
  signal validator
- v7 (SCENARIO-12/13/19): P1 spread/redir
  variants
- v8 (SCENARIO-16/17): P2 weather + beatup
- v9 (SCENARIO-20): library closeout

---

## Next steps

After this closeout, per user direction,
the next possible work is:

1. **TERRAIN-1 — Terrain Basic
   Scenario** (P2, field control):
   - Custom team with a terrain setter
     (e.g., Indeedee-F with Psychic
     Terrain, Rillaboom with Grassy
     Terrain, Pincurchin with Electric
     Terrain)
   - Bot has some legal response
   - Only if user wants field control
   coverage
2. **PLANNER data generation** using
   existing scenarios:
   - Use the 9 active scenarios as a
     test suite for the planner's
     response logic
   - Run each scenario with various
     bot policies to generate training
     data
3. **Follow Me true variant**:
   - Scripted Follow Me (not Rage
     Powder)
   - Compare behavior with Rage Powder
     variant
4. **WP scenario in a different
   format**: not VGC 2026 Champions
5. **Earthquake framework-level
   changes**: detect grounded vs
   airborne, check move effectiveness

Per the user's closeout guidance, no
new code is implemented in
SCENARIO-20. The library is the source
of truth for the scenario coverage.
