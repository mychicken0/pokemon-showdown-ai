# Family A — Speed Setup Survival (TR / Tailwind)

## Scenario

Force the opp to use Trick Room or Tailwind on turn 2+.

## Edit History

### v1 (CURATED-2)

- **Opp team:** `team_opp_sinistcha_v1.json` — copy of
  VGC top-200 idx 41 (`pikalytics_rank_045`).
  Has Sinistcha with TR + Strength Sap + Rage Powder +
  Protect. Sinistcha's Kasib Berry gives it a Ghost/Dark
  resistance (defensive item). Strength Sap can heal.
  Rage Powder redirects attacks. Trick Room sets up.
- **Our team:** `team_our_sinistcha_v1.json` — same team
  (mirror). Both sides have the same 6 mons. This is the
  simplest "scenario forcing" test: confirm the runner
  can wire custom teams. Scenario validity (does TR fire?)
  is measured per battle.

## Setup User

Sinistcha (Ghost/Grass, Hospitality ability):
- Matcha Gotcha (STAB Ghost/Grass spread)
- Strength Sap (heal + -1 ATK)
- Rage Powder (redirect)
- Trick Room (speed setup)

## Constraints

- **No edit to bot's scoring function.**
- **No edit to bot's team.** v1 uses mirror, which is
  the simplest "our team".
- **No stat / ability / item buffs.**
- **No random doubles / randombattle.**

## Pass Criteria (per COUNTER-4 design §6 family A)

| criterion | threshold |
|---|---|
| Both battles `status=ok` | 2/2 |
| Audit JSONL files exist (treatment + baseline) | 4 files |
| `opponent_used_trickroom` OR `opponent_used_tailwind` > 0 | ≥ 1 (any turn) |
| Setup user was on field at the turn the move was used | required |

## Status

- v1 created
- 1-pair validation probe pending
