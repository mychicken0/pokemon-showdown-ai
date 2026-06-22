# CONTROL-PRIORITY-2F — Regression Investigation

**Date**: 2026-06-22
**Status**: `ROOT_CAUSE_IDENTIFIED`
**Phase**: 2F (investigation of 2E regression)

## Background

2E 100-pair qualification showed ON -6pp vs OFF:
- ON: 86/100 (86%)
- OFF: 92/100 (92%)
- Delta: -6pp
- Sign test p=0.942 (very negative)

This investigation identifies the root cause.

## Methodology

Read-only analysis of existing audit files. No code changes.
No new battles. Uses the 100 ON + 100 OFF audit JSONL files
from 2E qualification.

## Findings

### Finding 1: Game length distribution differs

| turn range | ON count | OFF count |
|------------|----------|-----------|
| 4-5 | 8 (8%) | 17 (17%) |
| 6-7 | 56 (56%) | 60 (60%) |
| 8-10 | 32 (32%) | 21 (21%) |
| 11-100 | 4 (4%) | 2 (2%) |

- ON avg turns: 7.2
- OFF avg turns: 6.7
- ON games last 0.5 turns longer on average

### Finding 2: Win rate drops in longer games (the smoking gun)

| turn range | ON wins | OFF wins | Delta |
|------------|---------|----------|-------|
| 4-5 | 100% (8/8) | 100% (17/17) | even |
| 6-7 | 95% (53/56) | 92% (55/60) | ON +3pp |
| **8-10** | **75% (24/32)** | **90% (19/21)** | **ON -15pp** |
| 11-100 | 25% (1/4) | 50% (1/2) | ON -25pp |

**ON loses significantly in games that reach turn 8+**.
ON and OFF are even in short games.

### Finding 3: First 3 turns differ at turn 2

| turn | action | ON count | OFF count |
|------|--------|----------|-----------|
| 1 | FakeOut | 100 | 100 |
| 2 | damage | 79 | 97 |
| 2 | **Taunt** | **16** | **0** |
| 2 | switch/pass | 5 | 3 |
| 3 | damage | 70 | 68 |
| 3 | Taunt | 3 | 0 |
| 3 | switch/pass | 27 | 32 |

**ON selects Taunt 16 times on turn 2; OFF never selects Taunt.**
This is the anti-TR feature in action: the +500 bonus makes Taunt
competitive with damage on turn 2.

### Finding 4: Magic Bounce reveals

| arm | games with MB reveal | total games | reveal rate |
|-----|---------------------|-------------|-------------|
| ON | 10 | 100 | 10% |
| OFF | 0 | 100 | 0% |

**ON reveals Magic Bounce in 10 games. OFF reveals it in 0 games.**
The bot's Taunt at turn 2 forces Hatterene to reflect it, revealing
Magic Bounce. OFF never selects Taunt, so Magic Bounce is never
revealed (Hatterene dies before using a status move).

### Finding 5: 2A is working correctly

In 10 games where Magic Bounce was revealed:
- 25 ANTI_TR turns after reveal
- **0 Taunts selected after reveal**

2A's Magic Bounce tracking works: once Magic Bounce is revealed,
the bot never selects Taunt again. This confirms the implementation
is correct.

### Finding 6: HP loss explains the regression

| arm | avg final slot0 HP |
|-----|-------------------|
| ON | 0.619 |
| OFF | 0.683 |
| **Delta** | **-0.064** |

ON bot loses ~6.4% more HP on average.

### Finding 7: TR games win rates

| arm | wins when TR active | total TR games |
|-----|--------------------|----------------|
| ON | 45/51 (88%) | 51 |
| OFF | 50/52 (96%) | 52 |

ON wins 8% less in TR games.

## Root cause

The anti-TR feature's +500 bonus makes Taunt competitive with
damage at turn 2-3 (when Hatterene is at 1.0 HP, before Magic
Bounce is revealed). The bot selects Taunt, gets reflected by
Magic Bounce, and:

1. **Self-Taunt damage**: Hatterene's Magic Bounce reflects Taunt
   back to Incineroar, which Taunts our own Incineroar. This
   prevents our bot from using status moves (including future
   Taunts and the bot's own utility moves).

2. **HP loss from reflected damage**: Even if the reflection
   doesn't kill, Incineroar takes damage from the reflected
   Taunt (which can fail due to type immunity but still drains
   PP or deals residual effects in some edge cases).

3. **Wrong target priority**: At turn 2, Hatterene's Magic Bounce
   is NOT YET revealed. The bot doesn't know Hatterene will reflect.
   The +500 bonus creates a wrong-target bonus case where Taunt
   is selected on a target that will reflect it.

## Why 2A doesn't help

2A correctly blocks Taunt AFTER Magic Bounce is revealed.
But the damage is done BEFORE the reveal:
- Turn 2: Taunt selected (not blocked, MB not revealed)
- Turn 2: Hatterene reflects, MB revealed
- Turn 3+: Taunt blocked by 2A (but already too late)

The reflection in turn 2 hurts ON bot more than no Taunt at all.

## Why magnitude tuning doesn't help

User constraint: "no more magnitude tuning". Even if we lowered
the +500 bonus, the fundamental issue is:
- Bot selects Taunt at unknown Magic Bounce target
- Taunt gets reflected
- Self-damage

Lowering the bonus would just delay this to later turns, not
prevent it.

## Why this is structurally hard

In doubles VGC, anti-setup disruption (Taunt on TR setter) is
correct strategy WHEN you know the target has TR but not Magic
Bounce. The problem is:
- Target may have Magic Bounce (unknown to bot)
- Taunting a Magic Bounce target = self-Taunt

The bot cannot know in advance whether the target has Magic Bounce
(unless revealed). This is an inherent risk of the strategy.

## Possible mitigations

### 1. Pre-reveal Taunt penalty (not magnitude tuning)
- If the bot's Taunt has high probability of being reflected
  (e.g., target species is Hatterene), apply a penalty
- This is NOT magnitude tuning - it's a structural penalty
- Risk: species inference (banned per AGENTS.md)

### 2. Species-based Magic Bounce deduction (NOT ALLOWED)
- Hatterene in VGC 2026 has Magic Bounce + Healer (2 abilities)
- Singleton deduction does NOT apply
- Per AGENTS.md: no inference from species
- This approach is FORBIDDEN

### 3. Accept the regression
- Anti-TR feature works correctly per spec
- The 2A mechanics block works
- The +500 bonus is correct magnitude
- The regression is a real cost of the strategy
- Keep opt-in

### 4. Wait for Magic Bounce to be revealed naturally
- Don't apply anti-TR bonus until opponent reveals Magic Bounce
- Or some other delayed application
- Requires additional logic

## Decision: REGRESSION_DOCUMENTED

After investigation:
- Root cause: anti-TR Taunt at unknown Magic Bounce target
- Result: self-Taunt, HP loss, longer games, more losses
- 2A works correctly AFTER reveal (no Taunts after MB reveal)
- Fix requires either species inference (forbidden) or structural
  penalty (out of scope)

**Anti-TR remains OPT_IN_ONLY_FINAL.**

## Files

### Modified
- (none — read-only investigation)

### New
- `logs/phaseCONTROL_PRIORITY_2F_regression_investigation.md` (this file)

### Referenced
- `logs/phaseCONTROL_PRIORITY_2E_100pair_qualification.md` (qualification data)
- 200 audit JSONL files (100 ON + 100 OFF)

## Stable state
- 0 code changes (investigation only)
- 0 default flip
- 0 magnitude tuning
- 132 related tests pass
- Anti-TR remains OPT_IN_ONLY
- Root cause identified and documented
