# Scenario Library Index

This index lists all scenarios in the
scripted scenario framework. Each
scenario is a JSON file that defines:

- A scripted opponent action
  (e.g., Trick Room, Heat Wave, Rage
  Powder)
- The opposing team's lead
- A list of validators (post-battle
  checks)

The framework uses the canonical
signal from the baseline audit
(scripted opp's perspective). See
[Framework policy](#framework-policy)
below.

## Active scenarios (6)

| # | scenario_id | family | opp lead | scripted move | bot response legal | status |
|---|---|---|---|---|---|---|
| 1 | `anti_tr_basic` | anti_tr | Hatterene + Blastoise | Trick Room | Taunt (Zoroark-H) | PASS |
| 2 | `anti_tw_basic` | anti_tw | Whimsicott + Kingambit | Tailwind | Taunt (Zoroark-H) | PASS |
| 3 | `anti_stat_boost_basic` | anti_boost | Kingambit + Incineroar | Swords Dance | Taunt (Zoroark-H) | PASS |
| 4 | `spread_def_heat_wave` | spread_def | Volcarona + Blastoise | Heat Wave | Wide Guard (Torterra) | PASS |
| 5 | `redir_followme_basic` | redir | Sinistcha + Steelix | Rage Powder | Heat Wave (Volcarona) | PASS |
| 6 | `spread_def_rock_slide` | spread_def | Tyranitar + Steelix | Rock Slide | Wide Guard (Torterra) | PASS |

### Notes on individual scenarios

**`anti_tr_basic`** (v6, family 1):
opponent scripts Trick Room (Hatterene
+ Blastoise); bot has Taunt or Encore
legal (Zoroark-H, Whimsicott).

**`anti_tw_basic`** (v2, family 2):
opponent scripts Tailwind (Whimsicott
+ Kingambit); bot has Taunt legal
(Zoroark-H).

**`anti_stat_boost_basic`** (v2,
family 3): opponent scripts Swords
Dance (Kingambit + Incineroar); bot
has Taunt legal (Zoroark-H).

**`spread_def_heat_wave`** (v2, family
4): opponent scripts Heat Wave
(Volcarona + Blastoise); bot has
Wide Guard legal (Torterra).

**`redir_followme_basic`** (v2, family
8): **naming/semantic mismatch —
actual scripted move is Rage Powder,
not Follow Me**. The scenario name
follows the SCENARIO-6 design's
family-level naming (``redir_followme_basic``
covers both Follow Me and Rage
Powder). The basic implementation
starts with Rage Powder (because
Sinistcha has it; Rage Powder has
higher priority than Follow Me).
The Follow Me variant would be a
separate scenario (deferred). Bot
has Heat Wave legal (Volcarona) as
an AoE response.

**`spread_def_rock_slide`** (v2,
family 4): opponent scripts Rock
Slide (Tyranitar + Steelix); bot has
Wide Guard legal (Torterra).

## Probes (1)

| scenario_id | family | purpose |
|---|---|---|
| `anti_spread_heat_wave_probe` | spread_def | pre-library probe (SCENARIO-10A) for the Heat Wave + Wide Guard legality test. The library entry is `spread_def_heat_wave`. |

## Deferred scenarios (5)

| family | scenario_id (proposed) | reason |
|---|---|---|
| spread_def | `spread_def_earthquake` | Earthquake has grounded / Levitate / Flying type detection requirements. Audit logger needs type/ability data. See `logs/phaseSCENARIO14_earthquake_deferred_report.md`. |
| redir | `redir_followme` (true Follow Me variant) | Rage Powder covers basic redirection; Follow Me is +0 priority and may be outsped by faster mons. Different script from Rage Powder. |
| beatup_justified | `beatup_justified_basic` | P2 family; only 1 Justified mon in curated teams (Gallade). Needs custom team. |
| wp | `wp_super_effective_basic` | P2 family; 0 Weakness Policy holders in curated teams. Needs custom team. |
| weather | `weather_rain_basic` | P2 family; 0 explicit weather setters in curated teams. Needs custom team. |

## Framework policy

### Canonical signal (Option C)

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

### Cross-check

When the treatment audit is available,
the validator cross-checks
``opponent_actions.opponent_used_X``
against the canonical:

- Treatment True + canonical True =
  ``bot_opp_action_gap=False`` (both
  agree)
- Treatment False or None + canonical
  True = ``bot_opp_action_gap=True``
  (gap detected; canonical wins)
- Treatment True + canonical False =
  ``passed=False`` (canonical says
  didn't fire; this is a hard fail)

### References

- `logs/phaseSCENARIO11_p1_review_spread_signal_gap_report.md` —
  policy decision
- `logs/phaseSCENARIO11b_option_c_validator_report.md` —
  validator implementation
- `scenario_probe.py` — validator
  implementation

## Validator types

| type | description |
|---|---|
| `expected_scripted_action` | Option C canonical signal check. Reads baseline `scripted_actions`; cross-checks treatment `opponent_actions`. Sets `bot_opp_action_gap`. **Preferred for scripted scenarios.** |
| `expected_opp_action_used` | Legacy: reads treatment `opponent_actions.opponent_used_X` only. Does not work for scripted scenarios (the field is empty). Kept for backward compatibility. |
| `expected_audit_signal` | Reads `state_snapshot.X` from the audit. Used for non-scripted fields. |
| `expected_bot_legal_response` | Reads the bot's `v2l1_legal_action_keys_slotN` to confirm a move is legal in some turn. |
| `no_script_failures` | Skeleton: always passes. Real implementation would check `script_failures` from the baseline. |

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

### Required fields

- ``scenario_id`` (str): must match
  the filename (sans .json)
- ``description`` (str)
- ``version`` (int)
- ``our_team_file`` (str): path to a
  curated team file
- ``opp_team_file`` (str): path to a
  curated team file
- ``lead`` (object): maps
  ``opp_slot_0`` / ``opp_slot_1`` to
  species names
- ``script`` (object): maps turn
  numbers to actions
- ``validators`` (list): each
  validator has ``name``, ``type``,
  and type-specific fields

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

## File map

```
data/curated_teams/scenarios/
├── SCENARIO_INDEX.md                    # this file
├── anti_tr_basic.json                   # scenario 1
├── anti_tw_basic.json                   # scenario 2
├── anti_stat_boost_basic.json           # scenario 3
├── spread_def_heat_wave.json            # scenario 4
├── redir_followme_basic.json            # scenario 5
├── spread_def_rock_slide.json           # scenario 6
├── anti_spread_heat_wave_probe.json     # probe (SCENARIO-10A)
└── family_A_speed_setup/                # unrelated (Phase 6 setup)

logs/
├── phaseSCENARIO5_v22_report.md          # P0 family 1
├── phaseSCENARIO7_anti_tw_basic_report.md  # P0 family 2
├── phaseSCENARIO8_anti_stat_boost_basic_report.md  # P0 family 3
├── phaseSCENARIO9_p0_framework_closeout_report.md  # P0 closeout
├── phaseSCENARIO10A_p1_spread_heat_wave_probe_report.md  # P1 probe
├── phaseSCENARIO10_spread_def_heat_wave_report.md  # P1 family 4
├── phaseSCENARIO11_p1_review_spread_signal_gap_report.md  # P1 review
├── phaseSCENARIO11b_option_c_validator_report.md  # Option C validator
├── phaseSCENARIO12_redir_followme_basic_report.md  # P1 family 8
├── phaseSCENARIO13_spread_def_rock_slide_report.md  # P1 family 4 variant
├── phaseSCENARIO14_earthquake_deferred_report.md  # P1 family 4 deferred
└── phaseSCENARIO15_p1_closeout.md       # P1 closeout (this phase)
```

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
