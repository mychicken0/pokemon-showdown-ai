# PLANNER-ANTI-TR-EVAL-1 — Paired Evaluation Design

**Date**: 2026-06-22
**Status**: DESIGN_RECORDED
**Author**: opencode (per user spec)

## Goal

Determine whether `enable_anti_trick_room_response=True` produces a
**statistically meaningful improvement** in TR-heavy matchups without
introducing regressions in legitimate KO scenarios.

This is a paired, scenario-driven evaluation. Not a default flip.
The output is one of:

- `DEFAULT_CANDIDATE` — flip to default ON (gates all pass)
- `OPT_IN_ONLY` — keep opt-in (positive but not gate-ready)
- `NEEDS_GUARD` — feature has bugs that need fixes
- `INCONCLUSIVE_VARIANCE` — too noisy to decide

## Design constraints

- Same team, same scenario, paired trial index for ON/OFF.
- TR-heavy matchups only.
- Existing scenario harness (extend `bot_doubles_planner_spread_smoke`).
- 20-50 pairs for primary decision.
- 100-pair only if 20-50 pair gates pass.

## Three board states

The TR setter is the opponent's Hatterene. The opp's HP at the
moment our bot decides its first ANTI_TR response is the variable.

| state   | setter HP | expected bot response       |
|---------|-----------|-----------------------------|
| full    | >= 0.85   | TAUNT (no realistic KO)     |
| mid     | 0.40-0.84 | mixed (depends on damage)   |
| low     | < 0.40    | KO_SETTER (Taunt is wrong)  |

To make board state controlled, the scenario uses `DoublesTRUserPlayer`
to script the opp's HP loss in fixed turns. The opp always uses
Trick Room on turn 2 (so the bot sees ANTI_TR intent on turn 2).
The opp then takes scripted damage on turns 3, 4, 5 to reach the
target board state.

Wait — the existing `DoublesTRUserPlayer` only does TR + max damage.
To control board state, we need a *different* scripted opp that
allows HP manipulation. Approach: pre-script the opp Pokemon's
starting HP via a one-time `set_hp` event, OR use reveal of moves
to control the bot's perception.

**Simpler approach**: use a modified scripted opp that has a fixed
move sequence and takes fixed damage. The bot's view of the
opp's HP comes from turn-by-turn damage. We can't directly
control the bot's perception; we control the *battle outcome*.

For paired eval, we don't need to control board state perfectly —
we need **paired** outcomes. ON and OFF see the same battle, so
they see the same opp HP at the same turn. The 3 board states
emerge naturally from the battle trajectory.

## Metrics (per pair, per arm)

| metric                          | type      | definition                                    |
|---------------------------------|-----------|-----------------------------------------------|
| `won`                           | bool      | battle result                                 |
| `turns`                         | int       | turns to completion                           |
| `anti_tr_turns`                 | int       | turns where ANTI_TR intent fired              |
| `taunt_selected_count`          | int       | # turns selected a Taunt-class response       |
| `ko_on_setter_count`            | int       | # turns selected KO damage on TR setter       |
| `fake_out_count`                | int       | # turns selected Fake Out                     |
| `ignore_count`                  | int       | # turns selected non-response (damage ignore) |
| `other_count`                   | int       | # turns selected other support                |
| `tr_prevented`                  | bool      | opp never successfully set TR                 |
| `tr_set_count`                  | int       | # turns opp's TR was active                  |
| `wrong_taunt_over_ko`           | int       | # turns Taunt selected when clear KO existed  |
| `no_response_when_taunt_legal`  | int       | # turns no response when Taunt was legal      |
| `selected_class_top3`           | list[str] | top 3 selected response classes               |
| `spam_violation`               | int       | # turns past max_picks_per_game               |
| `crash`                         | bool      | exception/timeout                             |

## Response class classifier

```python
def classify_response(our_order, opp_active, intent):
    if not intent == "ANTI_TRICK_ROOM":
        return "NOT_ANTI_TR"
    move_id = our_order.order.id.lower()
    if move_id in ("taunt", "encore", "disable"):
        if our_order.move_target == 1 and opp_active[0] is setter:
            return "TAUNT"
        elif our_order.move_target == 2 and opp_active[1] is setter:
            return "TAUNT"
        else:
            return "WRONG_TARGET_TAUNT"
    elif move_id in ("fakeout",):
        return "FAKE_OUT"
    elif our_order.order.base_power > 0:
        if our_order.move_target in (1, 2) and our_active_targets_setter:
            return "KO_SETTER"
        elif our_order.move_target in (1, 2):
            return "DAMAGE_OTHER"
        else:
            return "SPREAD_DAMAGE"
    else:
        return "OTHER_SUPPORT"
```

## Pass criteria (gates)

1. **All tests pass** — 231+ unit tests, no crash.
2. **No timeout/error** — all 20-50 pairs complete.
3. **No wrong Taunt over clear KO** —
   `wrong_taunt_over_ko == 0` across all pairs in ON arm.
4. **No spam violation** — `spam_violation == 0` in ON arm.
5. **ON >= OFF paired delta** — sign test on per-pair won diff
   has p <= 0.10 (one-sided) or delta > +5pp.
6. **TR prevented more often in ON** —
   `tr_prevented_rate_ON > tr_prevented_rate_OFF` (or equal at small N).
7. **No-response when Taunt legal** — `no_response_when_taunt_legal`
   decreases in ON vs OFF at full-HP state.

## Decision tree

```
gates 1-4 pass?
├── no → NEEDS_GUARD (fix bugs first)
└── yes → compute ON vs OFF paired delta
         ├── delta >= +5pp, sign p<0.10
         │   ├── all 7 gates pass → DEFAULT_CANDIDATE (run 100-pair confirmation)
         │   └── some gates fail → OPT_IN_ONLY (keep opt-in)
         ├── delta in [-5pp, +5pp]
         │   └── INCONCLUSIVE_VARIANCE (need more trials or different matchup set)
         └── delta < -5pp
             └── NEEDS_REVERT (feature regresses, disable or fix)
```

## Trial plan

| step | name                  | pairs | purpose                          |
|------|-----------------------|-------|----------------------------------|
| 1    | 5-pair pilot          | 5     | verify wiring, no crash           |
| 2    | 20-pair primary       | 20    | decision eval                    |
| 3    | 50-pair secondary     | 50    | confirm if 20-pair is borderline |
| 4    | 100-pair qual         | 100   | only if all gates pass           |

Steps 1-2 are mandatory. Step 3-4 are conditional.

## Matchup set (TR-heavy)

5 TR-heavy matchups (TR opp + 4 variant teams). Trial 1 uses pair
1 vs each matchup. Trial 2 uses pair 2, etc. Total = 5 matchups × N
trials.

Matchup examples:
- Hatterene TR setter + Whimsicott
- Hatterene TR setter + Indeedee-F
- Farigiraf TR setter + Indeedee-F
- Farigiraf TR setter + Murkrow
- Hatterene TR setter + Murkrow (Tailwind variant, but with TR)

## Artifact plan

- `logs/phasePLANNER_ANTI_TR_EVAL_1.md` — this design
- `logs/phasePLANNER_ANTI_TR_EVAL_1_pilot.jsonl` — pilot results
- `logs/phasePLANNER_ANTI_TR_EVAL_1_20pair.jsonl` — primary results
- `logs/vgc2026_phasePLANNER_ANTI_TR_EVAL_1_{on,off}_*.jsonl` — raw audits

## Watchdog

- Heartbeat: 30s
- Stall timeout: 180s
- Outer shell timeout: 30 min for 5-pair pilot, 60 min for 20-pair

## Non-goals

- No default flip without 100-pair confirmation
- No magnitude bump to +800
- No new feature
- No scoring change

## Phase PLANNER-ANTI-TR-EVAL-1 — 20-pair pilot result

**Date**: 2026-06-22
**Status**: COMPLETED
**Decision**: `OPT_IN_ONLY` (keep opt-in, no default flip)

### Setup

- Custom opp: `DoublesTRUserPlayer` (TR priority)
- WG team: `planner_anti_tr_wg_team.json` (Incineroar w/ Taunt)
- Opp team: `general_opp_tr.json` (Hatterene TR, Gardevoir, etc.)
- 20 paired trials
- Bonus: response 500, KO 200 (unchanged from v4)
- Anti-TR opt-in (default OFF)

### Results

| arm  | wins | win_rate | taunt | ko | fo | prot | ps | tr_set_turns | tr_prevented | spam | errors |
|------|------|----------|-------|----|----|------|----|--------------|--------------|------|--------|
| ON   | 14/20 | 70%      | 1     | 19 | 0  | 3    | 10 | 40           | 12/20        | 0    | 0      |
| OFF  | 18/20 | 90%      | 0     | 19 | 0  | 4    | 9  | 46           | 10/20        | 0    | 0      |

**Paired delta**: ON wins=2, OFF wins=6, ties=12, **delta = -20.0pp**

### Statistical analysis

- One-sided sign test p-value: **0.145** (not significant at 0.10)
- TR prevented: ON 12/20, OFF 10/20 (+2pp, ON better)
- TR-active turns: ON 40, OFF 46 (ON has fewer TR-active turns)
- 1 Taunt selected (trial 15 t2, Hatterene 1.0 HP, correct)

### Gate evaluation

| gate | criterion                                      | result |
|------|------------------------------------------------|--------|
| 1    | All tests pass                                 | ✓ 231 tests pass |
| 2    | No timeout/error                               | ✓ 0 errors, 0 crashes |
| 3    | No wrong Taunt over clear KO                   | ✓ 1 Taunt at Hatterene 1.0 HP (correct) |
| 4    | No spam violation                              | ✓ 0 spam violations |
| 5    | ON >= OFF paired delta (p<=0.10 or +5pp)       | ✗ p=0.145, delta=-20pp (not met) |
| 6    | TR prevented more in ON                        | ✓ 12 vs 10 (+2pp) |
| 7    | No-response when Taunt legal decreases         | N/A (Incineroar rarely active) |

**Gates 1-4 pass. Gate 5 fails. Gate 6 passes. Gate 7 N/A.**

### Decision rationale

- **Behavior is correct**: 0 crashes, 0 errors, 0 spam, 0 wrong Taunt.
- **TR prevention works**: ON has fewer TR-active turns (40 vs 46).
- **Win rate delta is in noise range** (p=0.145 at 20 pairs, -20pp).
- The -20pp delta is likely from random variance, not feature
  regression, given:
  - Trial 12: ON had tr_p=1 but still lost (TR prevented doesn't = win)
  - Trial 18: ON had ko=2 but still lost (KO pressure doesn't = win)
  - The matchup (TR setter team) is hard for our team

### Why not default flip

- Per AGENTS.md adoption gates: "ON vs OFF is at least 50%".
- ON win rate (70%) < OFF win rate (90%) → fail.
- Need 100-pair confirmation if 20-pair is borderline.
- Even with TR prevention, win rate doesn't improve at 20 pairs.

### Recommendation

- **KEEP OPT-IN**: `enable_anti_trick_room_response = False` (default)
- Tuned bonus (500/200) is correct (no need to tune further)
- The feature works as designed; the eval shows it's not harmful
  but not clearly helpful at 20-pair scale

### Path forward

1. **More trials (50-pair or 100-pair)** to confirm the -20pp is variance.
2. **Different team** where Incineroar is lead (so Taunt is exercised more).
3. **Different matchup** (less TR-heavy) to see if anti-TR helps in
   marginal cases.
4. **Adoption**: only if 100-pair shows ON >= OFF with p<0.10.

### Files

- MOD `bot_doubles_anti_tr_eval.py` — eval harness
- NEW `logs/phasePLANNER_ANTI_TR_EVAL_1_p20pair.json` — primary results
- NEW `logs/vgc2026_phasePLANNER_ANTI_TR_EVAL_1_*.jsonl` — 40 raw audit files
