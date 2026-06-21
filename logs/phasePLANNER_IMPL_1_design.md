# PLANNER-IMPL-1 — Intent Detector Scoring Integration Design

## Status
**DESIGN ONLY** — no implementation, no scoring change, no default flip.
Per user plan: "design ว่า intent detector จะ feed เข้า scoring ยังไง, ยังไม่ implement scoring ทันที"

## Goal
Design how the per-turn intent detector (built in PLANNER-DATA-2/3) feeds into the joint order scoring of `bot_doubles_damage_aware.py` without breaking the existing v3d.1 PAUSE / adopted defaults.

## Existing assets

| asset | location | status |
|---|---|---|
| Per-move intent classifier | `bot_doubles_intent_classifier.py` | 33 tests pass, uncommitted |
| Per-turn intent detector (rule-based) | `scripts/run_intent_policy_dryrun.py` | PLANNER-DATA-2 (read-only) |
| Mixed dataset stability test | `scripts/run_mixed_stability_test.py` | PLANNER-DATA-3 (read-only) |
| Scenario library | `data/curated_teams/scenarios/` | 13 active, 8 families |
| Dataset | `logs/planner_dataset_v1.jsonl` | 101 rows |
| Mixed dataset | `logs/planner_mixed_stability_v1.jsonl` | 2155 rows |

## Architecture overview

```
                   ┌──────────────────┐
                   │ choose_move()    │
                   │  (per turn)      │
                   └────────┬─────────┘
                            │
              ┌─────────────┴──────────────┐
              ▼                            ▼
   ┌──────────────────┐         ┌─────────────────────┐
   │ Per-turn         │         │ Per-slot scoring    │
   │ IntentDetector   │         │ _score_action_impl  │
   │                  │         │  (existing)         │
   │ Input:           │         │                     │
   │ - scripted_act   │         │ Output:             │
   │ - revealed_moves │         │ slot_0_scores[]     │
   │ - weather        │         │ slot_1_scores[]     │
   │ - fields         │         └─────────┬───────────┘
   │                  │                   │
   │ Output:          │                   │
   │ IntentDecision   │                   │
   │  - intent        │                   │
   │  - confidence    │                   │
   │  - evidence      │                   │
   └────────┬─────────┘                   │
            │                             │
            │     ┌───────────────────────┘
            ▼     ▼
   ┌─────────────────────────────┐
   │ _compute_joint_scores()     │
   │                             │
   │ joint_score =               │
   │   score_1 + score_2 +       │
   │   intent_bonus_0 +          │
   │   intent_bonus_1            │
   │                             │
   │ (intent bonuses = 0 by      │
   │  default when feature OFF)  │
   └─────────────────────────────┘
```

## 1. Per-turn IntentDetector

### 1.1 Where it runs

`choose_move` → after state is read, before `slot_0_scores` / `slot_1_scores` are computed.

```python
# Pseudocode in choose_move
def choose_move(self, battle):
    if config.enable_intent_detector:
        intent_decision = self._intent_detector.detect(battle)
        # Stored on self for use in _compute_joint_scores
        self._current_intent_decision = intent_decision
    else:
        self._current_intent_decision = IntentDecision.NO_INTENT
    # ... existing flow continues
```

### 1.2 Input sources

| source | available in bot | source field |
|---|---|---|
| scripted actions | NO (only in test scenarios) | n/a |
| revealed opp moves | YES | `battle.opponent_active_pokemon[i].moves` |
| weather | YES | `battle.weather` (enum keys) |
| fields (terrain, trick_room) | YES | `battle.fields` (enum keys) |

Note: scripted actions are only available in test scenarios (not in real battles). The detector must work with revealed moves + weather + fields only in production.

### 1.3 Output schema

```python
@dataclass(frozen=True)
class IntentDecision:
    intent: str  # "ANTI_TRICK_ROOM" | "ANTI_TAILWIND" | "ANTI_STAT_BOOST"
                  # | "SPREAD_DEFENSE" | "REDIRECTION_RESPONSE"
                  # | "WEATHER_CONTROL" | "TERRAIN_CONTROL"
                  # | "COMBO_ENABLE" | "NO_INTENT"
    confidence: float  # 0.0 to 1.0
    matched_rule: str  # "speed_control_tr" | "stat_boost" | ...
    matched_moves: tuple[str, ...]  # which moves triggered
    trigger_evidence: dict  # full evidence: weather, fields, revealed_moves
    timestamp_turn: int  # battle.turn when detected

    @classmethod
    def NO_INTENT(cls, turn: int = 0) -> "IntentDecision":
        return cls("NO_INTENT", 0.0, "no_action", (), {}, turn)
```

### 1.4 Rule priority (deterministic, in priority order)

1. `trick_room` in fields → ANTI_TRICK_ROOM (high confidence 0.95)
2. `trickroom` in revealed moves → ANTI_TRICK_ROOM (med confidence 0.70)
3. `tailwind` in revealed moves → ANTI_TAILWIND (med confidence 0.70)
4. stat-boost move in revealed moves → ANTI_STAT_BOOST (med confidence 0.65)
5. spread move in revealed moves → SPREAD_DEFENSE (med confidence 0.60)
6. redirection move in revealed moves → REDIRECTION_RESPONSE (med confidence 0.70)
7. weather active → WEATHER_CONTROL (high confidence 0.85)
8. weather setter in revealed moves → WEATHER_CONTROL (low confidence 0.50)
9. terrain in fields → TERRAIN_CONTROL (high confidence 0.90)
10. terrain setter in revealed moves → TERRAIN_CONTROL (low confidence 0.50)
11. `beatup` in revealed moves + ally has Justified → COMBO_ENABLE (high confidence 0.85)
12. nothing → NO_INTENT (confidence 0.0)

Multi-intent: if multiple categories match, pick the highest confidence. Ties: priority order above.

### 1.5 Class sketch

```python
class IntentDetector:
    """Per-turn intent detector (pure function, side-effect free)."""

    SPEED_CONTROL_MOVES = {"trickroom", "tailwind"}
    STAT_BOOST_MOVES = {
        "swordsdance", "nastyplot", "calmmind", "quiverdance",
        "dragondance", "bulkup", "irondefense", "amnesia",
        "tailglow", "shellsmash", "agility", "rockpolish",
        "coil", "curse", "workup", "bellydrum", "clangoroussoul",
    }
    SPREAD_MOVES = {
        "heatwave", "rockslide", "earthquake", "dazzlinggleam",
        "surf", "mudslap", "eruption", "discharge", "waterpulse",
        "sludgewave", "boomburst", "makeitrain", "torchsong",
        "drainingkiss", "mysticalfire", "snarl", "thundercage",
    }
    REDIRECTION_MOVES = {"followme", "ragepowder", "spotlight"}
    TERRAIN_FIELDS = {"electric_terrain", "grassy_terrain",
                      "misty_terrain", "psychic_terrain"}
    WEATHER_FIELDS = {"raindance", "sunnyday", "sandstorm", "snowscape"}

    def detect(self, battle) -> IntentDecision:
        # Read weather, fields, revealed moves
        # Apply rules in priority order
        # Return IntentDecision
        ...
```

## 2. Scoring integration

### 2.1 Integration point

`bot_doubles_damage_aware.py:7540` (between slot scoring and joint scoring):

```python
# Existing (do not modify):
scored_joint_orders = self._compute_joint_scores(
    battle, config, joint_orders,
    slot_0_scores, slot_1_scores,
    _direct_absorb_blocked, _safety_blocked,
    _ally_redirect_blocked, _support_target_blocked=_support_target_blocked,
    _narrow_blocked=_narrow_blocked,
)

# New (additive, behind feature flag):
if config.enable_intent_detector:
    intent = self._current_intent_decision  # set in choose_move
    scored_joint_orders = self._apply_intent_bonus(
        scored_joint_orders, intent, config,
    )
```

### 2.2 Scoring effect: per-slot additive bonus

```python
def _apply_intent_bonus(
    self,
    scored_joint_orders: list,
    intent: IntentDecision,
    config,
) -> list:
    """Apply per-slot intent bonus to joint order scores.
    
    Multiplicative factors are NOT used (would amplify noise).
    Additive offset is bounded by config.intent_max_bonus_per_slot.
    """
    if intent.intent == "NO_INTENT":
        return scored_joint_orders
    
    # Compute per-slot bonus tables
    bonus_0, bonus_1 = self._compute_intent_bonus_per_slot(
        intent, config
    )
    
    max_bonus = config.intent_max_bonus_per_slot  # default 30.0
    bonus_0 = min(bonus_0, max_bonus)
    bonus_1 = min(bonus_1, max_bonus)
    
    # Apply bonus
    rescored = []
    for joint_order, joint_score, score_0, score_1 in scored_joint_orders:
        # Lookup action keys from joint_order
        action_key_0 = self._action_key(joint_order.first_order)
        action_key_1 = self._action_key(joint_order.second_order)
        
        # Apply per-slot intent bonus
        new_score_0 = score_0 + bonus_0[action_key_0]
        new_score_1 = score_1 + bonus_1[action_key_1]
        new_joint = new_score_0 + new_score_1
        
        rescored.append((joint_order, new_joint, new_score_0, new_score_1))
    
    # Re-sort by new joint score
    rescored.sort(key=lambda x: -x[1])
    return rescored
```

### 2.3 Per-intent bonus tables

```python
INTENT_BONUS_TABLES = {
    # ANTI_TRICK_ROOM: slot 0 should be the TR breaker
    "ANTI_TRICK_ROOM": {
        # Per-move bonuses (additive, in score units)
        "move:fakeout": {0: 25.0, 1: 5.0},   # slot 0 high, slot 1 small
        "move:imprison": {0: 30.0, 1: 0.0},
        "switch:fast": {0: 20.0, 1: 0.0},  # switch in fast mon
    },
    # ANTI_TAILWIND: slot 0 should set TW or KO TW setter
    "ANTI_TAILWIND": {
        "move:tailwind": {0: 25.0, 1: 5.0},
        "move:icywind": {0: 15.0, 1: 5.0},  # slow down opponent
    },
    # ANTI_STAT_BOOST: KO or Haze the booster
    "ANTI_STAT_BOOST": {
        "move:haze": {0: 30.0, 1: 0.0},
        "move:whirlwind": {0: 25.0, 1: 0.0},
        # Boost damaging moves against the booster (target_pos-aware)
    },
    # SPREAD_DEFENSE: protect against incoming spread
    "SPREAD_DEFENSE": {
        "move:protect": {0: 15.0, 1: 30.0},  # slot 1 protects more
        "move:wideguard": {0: 5.0, 1: 30.0},  # slot 1 is the WG
    },
    # REDIRECTION_RESPONSE: KO the redirection user
    "REDIRECTION_RESPONSE": {
        # Boost damaging moves against the redirection user
        # (requires target awareness — see "Target-aware" below)
    },
    # WEATHER_CONTROL: switch in weather counter
    "WEATHER_CONTROL": {
        "switch:tyranitar": {0: 25.0, 1: 0.0},  # Sand Stream counters rain
        "switch:torkoal": {0: 25.0, 1: 0.0},  # Drought counters rain
    },
    # TERRAIN_CONTROL: similar to weather
    "TERRAIN_CONTROL": {
        "switch:groundimmune": {0: 20.0, 1: 0.0},  # e.g. balloon Talonflame
    },
    # COMBO_ENABLE: enable Beat Up + Justified
    "COMBO_ENABLE": {
        "move:beatup": {0: 30.0, 1: 0.0},
    },
}
```

### 2.4 Target-aware bonus (REDIRECTION_RESPONSE, ANTI_STAT_BOOST)

Some intents need to know which opponent slot to target. The bonus table extends to:

```python
"REDIRECTION_RESPONSE": {
    "move:any": {
        # Bonus for hitting the redirection user
        # Need access to: which opp slot is the redirection user?
        # Detect via: if reveal shows "followme" in slot 0 moves, opp_slot 0 is redirector
        "target:redirector_slot": 20.0,
    },
},
```

Implementation: pass `battle.opponent_active_pokemon` to the bonus function. Identify redirector via revealed moves. Apply target-aware bonus.

### 2.5 What does NOT change

- `slot_0_scores` / `slot_1_scores` (existing per-slot scoring)
- `_compute_joint_scores` base score (only adds an additive offset)
- Safety blocks (intents never override safety)
- Hard blocks (intents never override)
- Existing flags (intents are additive, not replacement)

## 3. Config flags

```python
class DoublesDamageAwareConfig:
    # PLANNER-IMPL-1: Intent detector scoring integration
    # Default OFF: do not change scoring without explicit adoption
    enable_intent_detector: bool = False
    # When True, intent detector runs in choose_move and feeds into joint scoring
    # via additive per-slot bonus. NO safety / hard-block override.
    
    # Per-slot bonus cap (additive, in score units)
    # Default 30.0: matches meta_max_protect_bonus_per_active
    intent_max_bonus_per_slot: float = 30.0
    
    # Minimum confidence to apply bonus
    # Default 0.5: only fire when at least 50% confident
    intent_min_confidence: float = 0.5
```

Per AGENTS.md: "Adopted defaults" must include `enable_intent_detector = False` until all gates pass.

## 4. Audit / logging

New audit fields (observational only, do not affect scoring):

| field | type | description |
|---|---|---|
| `intent_label` | str | "ANTI_TRICK_ROOM" \| ... \| "NO_INTENT" |
| `intent_confidence` | float | 0.0 to 1.0 |
| `intent_matched_rule` | str | which rule fired |
| `intent_matched_moves` | list[str] | which moves triggered |
| `intent_bonus_slot0` | float | bonus applied to slot 0 (0.0 if NO_INTENT) |
| `intent_bonus_slot1` | float | bonus applied to slot 1 (0.0 if NO_INTENT) |
| `intent_changed_selection` | bool | True if intent bonus changed the selected joint order |

These are written to the doubles_decision_audit.jsonl. They are observational; they do not affect scoring when `enable_intent_detector = False`.

## 5. Adoption gates (per AGENTS.md)

### Gate 1: Static / unit tests
- All existing tests pass (currently 84 + 33 = 117)
- New tests for IntentDetector pure functions
- New tests for bonus table lookups

### Gate 2: Fixture test
- Build a battle state with `trick_room` field, verify IntentDecision(intent="ANTI_TRICK_ROOM", confidence=0.95)
- Build with `raindance` weather, verify WEATHER_CONTROL
- Build with `followme` revealed in opp slot 0, verify REDIRECTION_RESPONSE
- Build with no signals, verify NO_INTENT
- Verify bonus tables return correct values

### Gate 3: Targeted probe
- 1 battle, `enable_intent_detector = True`, verify:
  - intent decision is computed and logged
  - bonus is applied to joint score
  - selected joint order changes when intent bonus is high
  - safety blocks are NOT overridden
  - intent_changed_selection is recorded correctly

### Gate 4: Smoke (5-20 pairs, OFF vs ON)
- 5-20 paired battles
- Compare win rate: ON vs OFF
- Compare intent_changed_selection rate (should be <30% in smoke)
- Compare safety-block rate (should be unchanged)
- Pass if: win rate within ±2pp, no crashes, intent_changed < 30%

### Gate 5: Full benchmark (100-pair, OFF vs ON vs SafeRandom)
- 100 paired battles per arm
- Pass if:
  - ON vs OFF ≥ 50% win rate
  - ON vs Basic: does not regress > 2pp
  - ON vs SafeRandom ≥ 95%
  - intent_changed_selection < 50%
  - no crashes, stalls, or timeouts
  - safety blocks unchanged

### Gate 6: Adoption
- All 5 gates pass
- User explicitly approves flip
- `enable_intent_detector = True` is the new default

## 6. Risks

| risk | mitigation |
|---|---|
| Wrong intent fires → wrong scoring → bad decisions | Min confidence threshold (0.5); per-slot cap (30.0); feature flag OFF by default |
| Multi-intent conflict | Highest confidence wins; ties broken by priority order; emit only one intent |
| Confidence threshold tuning | Configurable `intent_min_confidence`; can be tuned post-smoke |
| Default flip breaks v3d.1 PAUSE | Feature OFF by default; flip only after Gate 5 passes |
| Intent bonus too strong | Per-slot cap (30.0); matches meta_max_protect_bonus_per_active |
| Intent bonus amplifies noise | Additive only (not multiplicative); safety blocks unchanged |
| Revealed-move data is sparse in older audits | Use weather/fields as primary signals; revealed moves are secondary |
| Older audit logger missing opp moves | Intent detector works with weather/fields only; revealed moves enhance signal |
| Test infrastructure doesn't support intent | New fixture tests for IntentDetector; existing tests unchanged |

## 7. Open questions

1. **Target-aware bonus**: how to detect "the redirection user" reliably? (visible via revealed moves + slot index)
2. **Switch scoring**: should intent also boost switches? (e.g., switch in Tyranitar for weather counter)
3. **Lead configuration**: should intent be aware of the lead? (e.g., "we lead Tyranitar vs rain" is different)
4. **Mid-turn updates**: what if intent changes mid-turn (e.g., opp reveals a new move)?
5. **Multi-intent emission**: should we allow multiple intents to fire with combined bonuses?

These are deferred to PLANNER-IMPL-2 / PLANNER-IMPL-3 (after Gate 5 passes).

## 8. Out of scope

- **No new scenarios**: existing 13 scenarios are sufficient
- **No new dataset generation**: PLANNER-DATA-1/2/3 are sufficient
- **No RL training**: not requested, not in scope
- **No bot v3d.1 changes**: v3d.1 still PAUSED
- **No new default flip**: feature OFF by default
- **No new audit fields beyond what is listed**: observational only

## 9. File-level changes (when implemented, NOT now)

| file | change |
|---|---|
| `bot_doubles_damage_aware.py` | Add IntentDetector class, _apply_intent_bonus method, config flags |
| `bot_doubles_intent_classifier.py` | Use existing classify_move_intent for move-level classification |
| `doubles_decision_audit_logger.py` | Add intent_label, intent_confidence, intent_bonus_slot0/1, intent_changed_selection fields |
| `test_*.py` | New tests for IntentDetector pure functions + bonus tables |
| `scenario_probe.py` | Optional: add intent detector to validators |

## 10. Stable state (no changes yet)

- 84 unit tests pass (current)
- 33 intent classifier tests pass (uncommitted, preserved)
- 0 scoring change
- 0 default flips
- 0 `test_51` touched
- 0 audit logger changes
- 0 `learned_preview_v3d1` promotion
- 0 V3d.1 PAUSE resumption
- 0 model artifacts

## 11. Next steps (per user plan)

- "ถ้า PLANNER-DATA-3 pass" — partial pass (4/5)
- "ค่อยไป PLANNER-IMPL-1 design" — THIS document
- "ยังไม่ implement scoring ทันที" — design only, no code change
- After this: discuss with user before any implementation

This design is awaiting user review. Per AGENTS.md: "Stop and request review before changing adopted defaults unless the user has already authorized adoption under explicit gates." Design changes do not require user authorization; implementation does.
