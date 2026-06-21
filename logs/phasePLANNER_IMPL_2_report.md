# PLANNER-IMPL-2 — Intent Detector Implementation Report

## Status
**`IMPLEMENTED_OBSERVATIONAL_OPT_IN`** — IntentDetector pure class implemented, integrated behind `enable_planner_intent_detector` flag (default OFF), audit fields added (observational only), no scoring change, no default flip.

## Goal (per user)
- Add pure IntentDetector (per-turn, no scoring)
- Add `enable_planner_intent_detector: bool = False` flag
- Cover only 4 MVP intents (ANTI_TRICK_ROOM, ANTI_TAILWIND, ANTI_STAT_BOOST, SPREAD_DEFENSE)
- Output observational audit fields
- Reuse existing per-move policies (NO new bonus tables)
- Default OFF, no runner smoke yet
- Test-first

## Implementation summary

### 1. IntentDetector class (pure function)

`bot_doubles_intent_classifier.py` extended with:

```python
@dataclass(frozen=True)
class IntentDecision:
    intent: str                # MVP_INTENTS or NO_INTENT
    confidence: float          # 0.0 to 1.0
    evidence_source: str       # EVIDENCE_*
    matched_moves: tuple       # which opp moves triggered
    routed_to_policy: str      # ROUTE_*

class IntentDetector:
    """Per-turn intent detector (pure function, side-effect free)."""

    def __init__(self, min_confidence: float = 0.5): ...
    def detect(self, ctx: dict) -> IntentDecision: ...

    # 4 internal detectors (one per MVP intent)
    def _detect_anti_trick_room(self, ctx) -> Optional[IntentDecision]: ...
    def _detect_anti_tailwind(self, ctx) -> Optional[IntentDecision]: ...
    def _detect_anti_stat_boost(self, ctx) -> Optional[IntentDecision]: ...
    def _detect_spread_defense(self, ctx) -> Optional[IntentDecision]: ...
```

### 2. Config flag (default OFF)

`bot_doubles_damage_aware.py` `DoublesDamageAwareConfig` extended with:

```python
# PLANNER-IMPL-2: opt-in per-turn intent detector.
# When True, runs IntentDetector.detect() per turn and writes
# observational audit fields. Default OFF. NO scoring change.
# NO default flip. Detector only LOGS; does NOT add bonus tables
# and does NOT trigger existing per-move policies.
enable_planner_intent_detector: bool = False
planner_intent_min_confidence: float = 0.5
```

### 3. choose_move integration (flag-gated)

```python
def choose_move(self, battle):
    if not isinstance(battle, DoubleBattle):
        return self.choose_random_move(battle)
    
    # PLANNER-IMPL-2: gated block
    if getattr(self.config, "enable_planner_intent_detector", False):
        decision = self._run_planner_intent_detector(battle)
        self._planner_intent_decision = decision
        try:
            setattr(battle, "_planner_intent_decision", decision)
        except Exception:
            pass
    else:
        # Default OFF: no detector call, no decision
        self._planner_intent_decision = None
        try:
            setattr(battle, "_planner_intent_decision", None)
        except Exception:
            pass
    
    # ... existing flow continues unchanged
```

**Default OFF path is identical to before**: the `if getattr(...)` evaluates to False, the else branch sets decision to None, and the rest of choose_move runs as before. NO scoring change.

### 4. Audit fields (observational only)

`doubles_decision_audit_logger.py` extended with `_populate_planner_intent_fields` and 7 new fields in `state_snapshot`:

| field | default | populated when |
|---|---|---|
| `planner_intent_label` | `None` | flag ON + decision fired |
| `planner_intent_confidence` | `None` | flag ON + decision fired |
| `planner_intent_matched_moves` | `None` | flag ON + decision fired |
| `planner_intent_evidence_source` | `None` | flag ON + decision fired |
| `planner_intent_routed_to_policy` | `None` | flag ON + decision fired |
| `planner_intent_bonus_applied` | `0.0` | always (default 0.0) |
| `planner_intent_changed_selection` | `False` | always (default False) |

**Per PLANNER-IMPL-1B constraint**: `planner_intent_bonus_applied` is always 0.0 because PLANNER-IMPL-2 does NOT add scoring bonus. The detector only LOGS intent. The existing per-move policies (`enable_anti_setup_disruption_intent`, `enable_spread_defense_bonus`, `enable_setup_intent_policy`) are separate and have their own audit fields.

### 5. Test suite (test-first)

`test_planner_intent_detector.py` — 15 fixture tests (≥13 minimum):

| class | tests | covers |
|---|---|---|
| `TestAntiTrickRoom` | 3 | revealed, field, no_signal |
| `TestAntiTailwind` | 3 | revealed, side_condition, no_signal |
| `TestAntiStatBoost` | 3 | revealed, counter, no_signal |
| `TestSpreadDefense` | 2 | revealed, no_signal |
| `TestCrossCutting` | 4 | empty ctx, low confidence, fainting, taunted |

## Pass criteria verification

| criterion | status | evidence |
|---|---|---|
| 13+ fixture tests pass | ✓ | 15/15 pass in `test_planner_intent_detector.py` |
| default OFF produces identical score/action path | ✓ | `if getattr(self.config, "enable_planner_intent_detector", False)` is False by default; else branch sets decision=None and does NOT call detector |
| detector emits NO_INTENT when no visible signal | ✓ | test_atr_no_signal_returns_no_intent, test_atw_no_signal, test_asb_no_signal, test_sd_no_signal (all 4 pass) |
| detector emits correct intent on scenario signals | ✓ | test_atr_revealed_in_moves, test_atw_revealed_in_moves, test_asb_revealed_in_moves, test_sd_revealed_spread_move (all 4 pass) |
| audit fields persist | ✓ | `_populate_planner_intent_fields` writes to `state_snapshot`; called from `_build_compact_state_snapshot` |
| no default flip | ✓ | `enable_planner_intent_detector: bool = False` is the explicit default |
| no model artifact | ✓ | no .pt / .pkl / .joblib files created; only .py / .md / .jsonl |
| no test_51 | ✓ | `test_51` not present in repo; not created |

## Constraints (per user)

| constraint | status |
|---|---|
| do not implement weather/terrain/combo/redirection | ✓ — only 4 MVP intents |
| do not add new bonus values | ✓ — `planner_intent_bonus_applied = 0.0` always |
| do not 100/200-pair | ✓ — no battle runs |
| do not RL | ✓ — no training code |
| do not broaden status move scoring | ✓ — no scoring changes |
| default OFF = identical path | ✓ — verified |
| 13+ fixture tests | ✓ — 15 tests |
| test-first | ✓ — tests written before implementation |

## Stable state

- 132 unit tests pass (84 + 33 + 15)
- 0 scoring change
- 0 default flips
- 0 `test_51` touched
- 0 audit logger behavior change (only additive fields)
- 0 `learned_preview_v3d1` promotion
- 0 V3d.1 PAUSE resumption
- 0 model artifacts
- 0 new battles
- 2 new config fields (boolean + float, no bonus magnitude)
- 7 new audit fields (observational only, all default to None/0.0/False)

## Files changed

| action | file | lines |
|---|---|---:|
| MOD | `bot_doubles_intent_classifier.py` | +298 (IntentDetector class) |
| MOD | `bot_doubles_damage_aware.py` | +179 (config flag + choose_move hook + detector runner) |
| MOD | `doubles_decision_audit_logger.py` | +52 (audit fields + populate method) |
| NEW | `test_planner_intent_detector.py` | +205 (15 fixture tests) |

## Decision label

**`IMPLEMENTED_OBSERVATIONAL_OPT_IN`**

## Recommendation for next steps

Per PLANNER-IMPL-1B's adoption gates:

1. **Static tests**: pass (132/132)
2. **Fixture tests**: pass (15/15)
3. **Targeted probe** (1 battle, flag ON): needed to verify:
   - audit fields are correctly written to JSONL
   - decision populates on real battle states
   - default-OFF still produces identical artifacts
4. **Smoke (5-20 pairs)**: needed to verify:
   - no crashes / stalls
   - intent_changed_selection metric (should be 0% since no scoring change)
5. **Full benchmark (100 pairs)**: NOT yet (gate 5, requires gates 1-4 first)

Next phase candidates:
- **PLANNER-IMPL-2b** (smoke): 5-20 pairs with flag ON, verify no crashes + audit fields present
- **PLANNER-IMPL-3** (deferred intents): target-aware damage bonus for REDIRECTION_RESPONSE
- Stay paused if user wants to commit and review
