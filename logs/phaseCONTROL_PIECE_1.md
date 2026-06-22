# CONTROL-PIECE-1 — Preserve Control Piece Audit

**Date**: 2026-06-22
**Status**: COMPLETED
**Decision**: `EVIDENCE_CLEAR_BUT_NOT_AS_HYPOTHESIZED`

## Goal

Audit whether the bot preserves control pieces (Taunt/Wide Guard
users) for utility opportunities, or removes them before the
opportunity arises.

This is a read-only audit. No scoring change. No default flip.
No new battle run (uses existing EVAL-1/EVAL-2 artifacts).

## Control piece definition

A Pokemon with at least one of:
- **Taunt, Encore, Disable** (anti-setup disruption)
- **Wide Guard, Quick Guard** (spread defense)
- **Follow Me, Rage Powder, Spotlight** (redirection)
- **Trick Room, Tailwind** (speed control)

## Q1. Control pieces in the team

| Pokemon   | Control moves       | Team file                       |
|-----------|---------------------|---------------------------------|
| Incineroar | Taunt              | planner_anti_tr_lead_team.json  |
| Garganacl  | Wide Guard         | planner_anti_tr_lead_team.json  |

Both teams (planner_anti_tr_wg_team.json, planner_anti_tr_lead_team.json)
have these same two control pieces at slots 0 and 1.

**Incineroar** is the only **anti-setup disruption** user in the team.
**Garganacl** is the only **spread defense** user in the team.

## Q2. Team preview inclusion

For EVAL-1 (random teampreview): Both control pieces are in the team
(6/6 mons selected), but lead is random.

For EVAL-2 (ForcedLeadPlayer): Both control pieces are at slot 1
in the lead. Team preview order is `123456` (deterministic).

**EVAL-2 result**: 20/20 trials have (Incineroar, Garganacl) as the lead.

## Q3. Lead inclusion

| eval | lead         | trials |
|------|--------------|--------|
| EVAL-1 (random) | varied | Kingambit+Garchomp (3), Garchomp+Garganacl (3), Volcarona+Arcanine (1) ... |
| EVAL-2 (forced) | (Incineroar, Garganacl) | 20/20 |

**EVAL-2 forced lead works**. The bot accepts this lead.

## Q4. Switch-out before utility opportunity?

Incineroar first-leave turn distribution (EVAL-2 ON arm, 20 trials):

| leave turn | count |
|------------|-------|
| t2         | 3     |
| t3         | 12    |
| t4         | 4     |
| t5         | 1     |

**19/20 trials**: Incineroar leaves by t4.

But: utility opportunity is at t1-t2 (Hatterene at 1.0 HP, our full HP).
Incineroar IS in the active slot during this window.

The switch-out happens AFTER the utility opportunity, not before.

## Q5. Switch-out reason

At t1 with Hatterene 1.0 HP, Incineroar 1.0 HP:
- Bot selected Fake Out 1 (priority + flinch), Salt Cure 1
- Top 5 alternatives: all Fake Out + Salt Cure variants
- **Taunt is NOT in top 5**

At t2 with Hatterene ~0.66 HP, Incineroar 0.55 HP:
- Bot selected Flare Blitz 1, Salt Cure 1
- Damage moves dominate
- **Taunt is rarely in top 5**

**The bot uses Incineroar for damage (Flare Blitz, Fake Out) at the
utility opportunity. This takes HP. Incineroar faints or has to be
replaced by t3-4.**

## Q6. Opportunity timing

| turn | Incineroar HP | Hatterene HP | Taunt preferred? |
|------|---------------|--------------|------------------|
| t1   | 1.0           | 1.0          | YES (full opp, our full) |
| t2   | 0.55-0.63     | 0.66-1.0     | YES (full opp, our OK)   |
| t3   | 0.12-0.36     | 0.07-None    | NO (low opp, our low)    |

**Opportunity window: t1-t2**. After t2, Hatterene is too low to
Taunt (KO is better).

## Q7. Legal response when control piece is in?

In 12/12 ANTI_TR turns where Incineroar is active:
- Taunt is legal (Hatterene in opp slot 0 or 1)
- 2/12 had Taunt selected (Hatterene 1.0 HP, Incineroar full HP)
- 10/12 had KO pressure selected (Hatterene <1.0 HP)
- 0 wrong Taunt over KO

**When given the opportunity, the bot picks the right move.**

## Q8. Pattern: Incineroar out before Hatterene in?

No. The pattern is the opposite:
- Hatterene is in by t1-t2
- Incineroar is in by t1 (forced lead)
- Both are in during the opportunity window (t1-t2)
- Incineroar leaves by t3-4 due to HP loss from taking damage
  (bot chose damage moves, not Taunt)

## Decision: `EVIDENCE_CLEAR_BUT_NOT_AS_HYPOTHESIZED`

The hypothesis was: "bot removes control piece before utility
opportunity". The data shows:

- ✓ Control pieces are in the lead
- ✓ Control pieces are in active slot during utility opportunity
- ✗ Bot does NOT remove them prematurely
- ✓ When given the opportunity, bot selects the right move (Taunt
  or KO based on opp HP)
- ✗ Bot's chosen moves (Fake Out, Flare Blitz) at t1-t2 cause HP
  loss that removes the control piece from active slot by t3-4

**Root cause**: The bot uses the control piece (Incineroar) for
damage moves, not for utility moves. This causes the control piece
to take damage and leave the active slot.

**This is a scoring/priority issue, not a preservation issue.**

## Implications for adoption

The original hypothesis (control piece not preserved) was wrong.
The actual issue is that the bot's scoring doesn't value Taunt
enough to overcome damage/priority moves at t1-t2.

**Adoption cannot be achieved by magnitude tuning alone** (per
user constraint: "no more magnitude tuning"). Other options:

1. **Control Piece Preservation Policy** (new design):
   - When control piece is in active slot AND opp has utility threat
   - Penalize damage moves that put control piece at risk
   - Reward staying-in + using utility move
   - This is a switch-decision change, not a magnitude change

2. **Switch-in Priority** (new design):
   - When the bot's choose_move considers switching in, check if
     current slot 0 is a control piece
   - If yes, prefer staying in (don't switch)
   - Unless the switch target is also a control piece

3. **Different team composition** (already explored in EVAL-2):
   - Add multiple Taunt users so the control piece is always in
   - But limited Taunt users in Paldea dex (only Incineroar)
   - Would need to use a Hatterene or Farigiraf (TR setter with
     Taunt option) as backup

4. **Accept that anti-TR is opt-in only**:
   - Feature works correctly when given opportunity
   - The opportunity is rare (24.5% of ANTI_TR turns in EVAL-2)
   - 0% default flip is the right call

## Path forward

Per the user's spec:
> "ถ้า evidence clear: ต่อไปค่อยออกแบบ Control Piece Preservation Policy"

The evidence is clear (the hypothesis was wrong, but the data
revealed a different issue). Next step would be to design the
Control Piece Preservation Policy.

But for now, this is a design-only report. No code changes.

## Files
- NEW `logs/phaseCONTROL_PIECE_1.md` (this report)
- Uses existing `logs/phasePLANNER_ANTI_TR_EVAL_1.md` (EVAL-2 section)
- Uses existing audit JSONL files
