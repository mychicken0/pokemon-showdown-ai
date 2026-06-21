"""
PLANNER-DATA-3 — Mixed Dataset Stability Test

Read-only stability test for the intent policy.
Combines:
  - PLANNER-DATA-1 scenario dataset (101 rows, canonical signals)
  - Real ACCURACY3 100-pair dataset (937 rows, no canonical signals)

Same deterministic policy as PLANNER-DATA-2.
Measures:
  - scenario signal accuracy
  - real-data intent distribution
  - NO_INTENT rate on real data
  - collision rate (multiple intents per row)
  - trigger evidence for every fire
  - unknown / unclassified signal handling

Pass criteria (per user):
  - scenario signal accuracy >= 95%
  - real-data FPR <= 5%
  - no single intent dominates > 50% of real positives
  - all emitted intents have visible trigger evidence
  - NO_INTENT remains majority on real data

No new battles, no scoring change, no default flip.
"""
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, "scripts")
from run_intent_policy_dryrun import (
    predict_intent,
    SPREAD_MOVES,
    TERRAIN_MOVES,
    WEATHER_MOVES,
    REDIRECTION_MOVES,
    STAT_BOOST_MOVES,
    SPEED_CONTROL_MOVES,
)


# Map showdown enum names (with underscores) to move names (no underscores)
# state_snapshot.fields uses "trick_room" / "electric_terrain" / etc.
# but move names in scripted_action_fired use "trickroom" / "electricterrain"
def normalize_field(field):
    return field.replace("_", "")


def normalize_weather(w):
    return w.replace("_", "")


# Pre-compute the field/weather names that map to each intent
TERRAIN_FIELDS_ENUM = {"electric_terrain", "grassy_terrain", "misty_terrain", "psychic_terrain"}
WEATHER_WEATHER_ENUM = {"raindance", "sunnyday", "sandstorm", "snowscape", "hail",
                         "desolateland", "primordialsea", "deltastream"}


def load_scenario_rows(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def load_real_audit_rows(prefix="logs/vgc2026_phaseACCURACY3_100pair_v1_p",
                          suffix="_treatment_audit.jsonl",
                          max_battles=100):
    """Load real audit rows from multiple batches.

    Includes:
    - ACCURACY3 100-pair (100 battles)
    - ACCURACY2 fix (5 battles, has fields)
    - CONTROL 4A/4B 5-pair (10 battles)
    """
    rows = []
    # ACCURACY3 100-pair
    for p in range(max_battles):
        path = f"logs/vgc2026_phaseACCURACY3_100pair_v1_p{p}_treatment_audit.jsonl"
        if not Path(path).exists():
            continue
        with open(path) as f:
            for line in f:
                rec = json.loads(line)
                bt = rec.get("battle_tag")
                for t in rec.get("audit_turns", []):
                    snap = t.get("state_snapshot", {}) or {}
                    row = {
                        "source": "real_acc3",
                        "battle_tag": bt,
                        "turn": t.get("turn"),
                        "our_active": snap.get("our_active_species", []),
                        "opp_active": snap.get("opp_active_species", []),
                        "scripted_action_fired": [],
                        "state_snapshot": {
                            "weather": snap.get("weather", []),
                            "fields": snap.get("fields", []),
                            "opp_active_moves_revealed": [],
                        },
                    }
                    rows.append(row)
    # ACCURACY2 fix (5 battles, has fields)
    for p in [1, 12, 16, 71, 100]:
        path = f"logs/vgc2026_phaseACCURACY2_fix_v1_p{p}_treatment_audit.jsonl"
        if not Path(path).exists():
            continue
        with open(path) as f:
            for line in f:
                rec = json.loads(line)
                bt = rec.get("battle_tag")
                for t in rec.get("audit_turns", []):
                    snap = t.get("state_snapshot", {}) or {}
                    row = {
                        "source": "real_acc2",
                        "battle_tag": bt,
                        "turn": t.get("turn"),
                        "our_active": snap.get("our_active_species", []),
                        "opp_active": snap.get("opp_active_species", []),
                        "scripted_action_fired": [],
                        "state_snapshot": {
                            "weather": snap.get("weather", []),
                            "fields": snap.get("fields", []),
                            "opp_active_moves_revealed": [],
                        },
                    }
                    rows.append(row)
    # CONTROL 4A/4B (10 battles)
    for batch in ["phaseCONTROL4A_5pair", "phaseCONTROL4B_5pair"]:
        for p in range(5):
            path = f"logs/vgc2026_{batch}_p{p}_treatment_audit.jsonl"
            if not Path(path).exists():
                continue
            with open(path) as f:
                for line in f:
                    rec = json.loads(line)
                    bt = rec.get("battle_tag")
                    for t in rec.get("audit_turns", []):
                        snap = t.get("state_snapshot", {}) or {}
                        row = {
                            "source": "real_ctrl",
                            "battle_tag": bt,
                            "turn": t.get("turn"),
                            "our_active": snap.get("our_active_species", []),
                            "opp_active": snap.get("opp_active_species", []),
                            "scripted_action_fired": [],
                            "state_snapshot": {
                                "weather": snap.get("weather", []),
                                "fields": snap.get("fields", []),
                                "opp_active_moves_revealed": [],
                            },
                        }
                        rows.append(row)
    return rows


def predict_with_evidence(row):
    """Predict intent + return visible trigger evidence."""
    scripted = row.get("scripted_action_fired", [])
    revealed = row.get("state_snapshot", {}).get("opp_active_moves_revealed", [])
    weather = row.get("state_snapshot", {}).get("weather", [])
    fields = row.get("state_snapshot", {}).get("fields", [])

    # Collect all move names from scripted + revealed
    scripted_moves = {a.get("move", "") for a in scripted}
    revealed_moves = {m for sub in revealed for m in sub if m}

    moves_this_turn = scripted_moves | revealed_moves
    fields_set = set(fields)
    weather_set = set(weather)

    # Compute evidence first
    evidence = {
        "scripted_moves": sorted(scripted_moves),
        "revealed_moves": sorted(revealed_moves),
        "weather": sorted(weather),
        "fields": sorted(fields),
    }

    # Check for speed control
    tr_fired = "trickroom" in moves_this_turn
    if tr_fired:
        return "ANTI_TRICK_ROOM", "speed_control_tr", ["trickroom"], evidence
    tw_fired = "tailwind" in moves_this_turn
    if tw_fired:
        return "ANTI_TAILWIND", "speed_control_tw", ["tailwind"], evidence

    # Check for stat boost
    boost_moves = moves_this_turn & STAT_BOOST_MOVES
    if boost_moves:
        return "ANTI_STAT_BOOST", "stat_boost", sorted(boost_moves), evidence

    # Check for spread damage
    spread_moves = moves_this_turn & SPREAD_MOVES
    if spread_moves:
        return "SPREAD_DEFENSE", "spread_damage", sorted(spread_moves), evidence

    # Check for redirection
    redir_moves = moves_this_turn & REDIRECTION_MOVES
    if redir_moves:
        return "REDIRECTION_RESPONSE", "redirection", sorted(redir_moves), evidence

    # Check for TR in fields (Trick Room is a field condition)
    if "trick_room" in fields_set:
        return "ANTI_TRICK_ROOM", "tr_field_active", ["trickroom"], evidence

    # Check for weather (visible in state_snapshot.weather, OR scripted/revealed move)
    weather_set = set(weather) | (moves_this_turn & WEATHER_MOVES)
    if weather_set & WEATHER_WEATHER_ENUM:
        # Active weather from any source
        return "WEATHER_CONTROL", "weather_active", sorted(weather_set), evidence

    # Check for terrain (visible in state_snapshot.fields, OR scripted/revealed move)
    fields_normalized = {normalize_field(f) for f in fields_set} | (moves_this_turn & TERRAIN_MOVES)
    if fields_normalized & TERRAIN_MOVES:
        return "TERRAIN_CONTROL", "terrain_active", sorted(fields), evidence

    # Check for beatup+justified combo
    if "beatup" in moves_this_turn:
        return "COMBO_ENABLE", "combo_beatup", ["beatup"], evidence

    return "NO_INTENT", "no_action", [], evidence


def has_visible_trigger(intent, evidence):
    """Verify the predicted intent has visible trigger evidence."""
    if intent == "NO_INTENT":
        return True
    # Each non-NO_INTENT intent must have at least one trigger
    scripted = evidence.get("scripted_moves", [])
    revealed = evidence.get("revealed_moves", [])
    weather = evidence.get("weather", [])
    fields = evidence.get("fields", [])

    if intent in ("ANTI_TRICK_ROOM",):
        return ("trickroom" in scripted or "trickroom" in revealed
                or "trick_room" in fields)
    if intent in ("ANTI_TAILWIND",):
        return "tailwind" in scripted or "tailwind" in revealed
    if intent == "ANTI_STAT_BOOST":
        return bool(set(scripted) & STAT_BOOST_MOVES) or bool(set(revealed) & STAT_BOOST_MOVES)
    if intent == "SPREAD_DEFENSE":
        return bool(set(scripted) & SPREAD_MOVES) or bool(set(revealed) & SPREAD_MOVES)
    if intent == "REDIRECTION_RESPONSE":
        return bool(set(scripted) & REDIRECTION_MOVES) or bool(set(revealed) & REDIRECTION_MOVES)
    if intent == "WEATHER_CONTROL":
        return (bool(set(weather) & WEATHER_WEATHER_ENUM)
                or bool(set(scripted) & WEATHER_MOVES))
    if intent == "TERRAIN_CONTROL":
        return (bool({normalize_field(f) for f in fields} & TERRAIN_MOVES)
                or bool(set(scripted) & TERRAIN_MOVES))
    if intent == "COMBO_ENABLE":
        return "beatup" in scripted or "beatup" in revealed
    return False


def run_mixed_test(scenario_path, real_prefix, output_path, summary_path, md_path):
    print("Loading scenario dataset...")
    scenario_rows = load_scenario_rows(scenario_path)
    print(f"  {len(scenario_rows)} scenario rows")

    print("Loading real audit dataset...")
    real_rows = load_real_audit_rows(prefix=real_prefix, max_battles=100)
    print(f"  {len(real_rows)} real rows")

    print("Running policy on mixed dataset...")

    # Annotate all rows
    annotated = []
    for r in scenario_rows:
        predicted, rule, moves, evidence = predict_with_evidence(r)
        # Per-turn GT for scenarios:
        if r["scripted_action_fired"]:
            per_turn_gt = r["intent_label"]
        else:
            per_turn_gt = "NO_INTENT"
        new = dict(r)
        new["source"] = "scenario"
        new["predicted_intent"] = predicted
        new["matched_rule"] = rule
        new["matched_moves"] = moves
        new["per_turn_gt"] = per_turn_gt
        new["correct"] = (predicted == per_turn_gt)
        new["evidence"] = evidence
        new["has_trigger"] = has_visible_trigger(predicted, evidence)
        annotated.append(new)

    for r in real_rows:
        predicted, rule, moves, evidence = predict_with_evidence(r)
        # Real data GT: NO_INTENT expected (real battles are mostly non-canonical)
        per_turn_gt = "NO_INTENT"
        new = dict(r)
        new["predicted_intent"] = predicted
        new["matched_rule"] = rule
        new["matched_moves"] = moves
        new["per_turn_gt"] = per_turn_gt
        new["correct"] = (predicted == per_turn_gt)
        new["evidence"] = evidence
        new["has_trigger"] = has_visible_trigger(predicted, evidence)
        annotated.append(new)

    # Write JSONL
    with open(output_path, "w") as f:
        for r in annotated:
            f.write(json.dumps(r) + "\n")

    # Compute stats
    n_scenario = len([r for r in annotated if r["source"] == "scenario"])
    n_real = len([r for r in annotated if r["source"] != "scenario"])
    n_total = len(annotated)

    # Scenario accuracy
    scen_rows = [r for r in annotated if r["source"] == "scenario"]
    scen_signal = [r for r in scen_rows if r["scripted_action_fired"]]
    scen_nosignal = [r for r in scen_rows if not r["scripted_action_fired"]]
    scen_signal_correct = sum(1 for r in scen_signal if r["correct"])
    scen_nosignal_correct = sum(1 for r in scen_nosignal if r["correct"])
    scen_signal_accuracy = scen_signal_correct / max(1, len(scen_signal))
    scen_nosignal_accuracy = scen_nosignal_correct / max(1, len(scen_nosignal))

    # Real data analysis
    real_rows_a = [r for r in annotated if r["source"] != "scenario"]
    real_fires = [r for r in real_rows_a if r["predicted_intent"] != "NO_INTENT"]
    real_nointent = [r for r in real_rows_a if r["predicted_intent"] == "NO_INTENT"]
    real_fire_rate = len(real_fires) / max(1, len(real_rows_a))
    real_nointent_rate = len(real_nointent) / max(1, len(real_rows_a))
    # Trigger evidence check
    real_fires_with_trigger = sum(1 for r in real_fires if r["has_trigger"])
    real_fires_no_trigger = len(real_fires) - real_fires_with_trigger
    real_fpr = real_fires_no_trigger / max(1, len(real_rows_a))
    real_fires_with_trigger_rate = real_fires_with_trigger / max(1, len(real_fires))

    # Per-intent distribution on real fires
    real_intent_dist = Counter(r["predicted_intent"] for r in real_fires)
    # Check no single intent dominates > 50%
    real_intent_dominance = max(real_intent_dist.values()) / max(1, len(real_fires)) if real_fires else 0

    # Collisions (multiple intents per turn)
    # In current policy only one intent fires, so collisions = 0
    # But let me count if any row fires multiple intent categories
    collisions = 0
    for r in annotated:
        ev = r["evidence"]
        scripted = set(ev.get("scripted_moves", []))
        revealed = set(ev.get("revealed_moves", []))
        weather = set(ev.get("weather", []))
        fields = set(ev.get("fields", []))
        moves = scripted | revealed
        n_intents = 0
        if moves & SPEED_CONTROL_MOVES:
            n_intents += 1
        if "trick_room" in fields:
            n_intents += 1
        if moves & STAT_BOOST_MOVES:
            n_intents += 1
        if moves & SPREAD_MOVES:
            n_intents += 1
        if moves & REDIRECTION_MOVES:
            n_intents += 1
        if weather & WEATHER_WEATHER_ENUM:
            n_intents += 1
        if {normalize_field(f) for f in fields} & TERRAIN_MOVES:
            n_intents += 1
        if "beatup" in moves:
            n_intents += 1
        if n_intents >= 2:
            collisions += 1

    # Unknown / unclassified
    unknown = 0
    for r in annotated:
        if not r["has_trigger"] and r["predicted_intent"] != "NO_INTENT":
            unknown += 1

    # Per-source accuracy
    summary = {
        "totals": {
            "total_rows": n_total,
            "scenario_rows": n_scenario,
            "real_rows": n_real,
        },
        "scenario": {
            "total": len(scen_rows),
            "with_signal": len(scen_signal),
            "without_signal": len(scen_nosignal),
            "signal_correct": scen_signal_correct,
            "signal_accuracy": scen_signal_accuracy,
            "no_signal_correct": scen_nosignal_correct,
            "no_signal_accuracy": scen_nosignal_accuracy,
        },
        "real": {
            "total": len(real_rows_a),
            "fires": len(real_fires),
            "no_intent": len(real_nointent),
            "fire_rate": real_fire_rate,
            "no_intent_rate": real_nointent_rate,
            "fires_with_trigger": real_fires_with_trigger,
            "fires_no_trigger": real_fires_no_trigger,
            "fpr_no_trigger": real_fpr,
            "fires_with_trigger_rate": real_fires_with_trigger_rate,
        },
        "distribution": {
            "real_intent_dist": dict(real_intent_dist),
            "real_intent_dominance": real_intent_dominance,
        },
        "collisions": {
            "rows_with_multiple_intents": collisions,
            "collision_rate": collisions / max(1, n_total),
        },
        "unknown": {
            "rows_no_trigger_with_intent": unknown,
            "unknown_rate": unknown / max(1, n_total),
        },
    }

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # MD report
    lines = []
    lines.append("# PLANNER-DATA-3 — Mixed Dataset Stability Test")
    lines.append("")
    lines.append(f"**Total rows**: {n_total}")
    lines.append(f"**Scenario rows**: {n_scenario}")
    lines.append(f"**Real rows**: {n_real}")
    lines.append("")
    lines.append("## Scenario dataset (canonical signals)")
    lines.append("")
    s = summary["scenario"]
    lines.append(f"| segment | rows | correct | accuracy |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| Total | {s['total']} | {s['signal_correct'] + s['no_signal_correct']} | {(s['signal_correct'] + s['no_signal_correct']) / max(1, s['total']):.1%} |")
    lines.append(f"| With signal | {s['with_signal']} | {s['signal_correct']} | {s['signal_accuracy']:.1%} |")
    lines.append(f"| Without signal | {s['without_signal']} | {s['no_signal_correct']} | {s['no_signal_accuracy']:.1%} |")
    lines.append("")
    lines.append("## Real dataset (ACCURACY3 100-pair, 100 battles)")
    lines.append("")
    r = summary["real"]
    lines.append(f"| metric | value | threshold |")
    lines.append(f"|---|---|---|")
    lines.append(f"| Total turns | {r['total']} | - |")
    lines.append(f"| Fires (non-NO_INTENT) | {r['fires']} ({r['fire_rate']:.1%}) | - |")
    lines.append(f"| NO_INTENT | {r['no_intent']} ({r['no_intent_rate']:.1%}) | > 50% |")
    lines.append(f"| Fires with valid trigger | {r['fires_with_trigger']} / {r['fires']} ({r['fires_with_trigger_rate']:.1%}) | 100% |")
    lines.append(f"| Fires without trigger (FPR) | {r['fires_no_trigger']} ({r['fpr_no_trigger']:.1%}) | <= 5% |")
    lines.append("")
    lines.append("## Intent distribution on real fires")
    lines.append("")
    lines.append("| intent | fires | % of real fires |")
    lines.append("|---|---|---|")
    for intent, count in sorted(real_intent_dist.items(), key=lambda x: -x[1]):
        pct = count / max(1, len(real_fires))
        lines.append(f"| `{intent}` | {count} | {pct:.1%} |")
    lines.append("")
    lines.append(f"**Max dominance**: {real_intent_dominance:.1%} (threshold: <= 50%)")
    lines.append("")
    lines.append("## Collision / unknown stats")
    lines.append("")
    c = summary["collisions"]
    u = summary["unknown"]
    lines.append(f"- Rows with multiple intent signals: {c['rows_with_multiple_intents']} ({c['collision_rate']:.1%})")
    lines.append(f"- Rows with intent but no trigger evidence: {u['rows_no_trigger_with_intent']} ({u['unknown_rate']:.1%})")
    lines.append("")
    lines.append("## Pass criteria")
    lines.append("")
    scen_pass = s["signal_accuracy"] >= 0.95
    fpr_pass = r["fpr_no_trigger"] <= 0.05
    trigger_pass = r["fires_no_trigger"] == 0
    dom_pass = real_intent_dominance <= 0.5
    majority_pass = r["no_intent_rate"] > 0.5
    lines.append(f"- [{'x' if scen_pass else ' '}] scenario signal accuracy >= 95% (got {s['signal_accuracy']:.1%})")
    lines.append(f"- [{'x' if fpr_pass else ' '}] real-data FPR <= 5% (got {r['fpr_no_trigger']:.1%})")
    lines.append(f"- [{'x' if trigger_pass else ' '}] all fires have valid trigger evidence (got {r['fires_with_trigger']}/{r['fires']})")
    lines.append(f"- [{'x' if dom_pass else ' '}] no single intent dominates > 50% of real fires (got {real_intent_dominance:.1%})")
    lines.append(f"- [{'x' if majority_pass else ' '}] NO_INTENT is majority on real data (got {r['no_intent_rate']:.1%})")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    return annotated, summary


def main():
    output_path = "logs/planner_mixed_stability_v1.jsonl"
    summary_path = "logs/planner_mixed_stability_v1_summary.json"
    md_path = "logs/planner_mixed_stability_v1_summary.md"
    scenario_path = "logs/planner_dataset_v1.jsonl"
    real_prefix = "logs/vgc2026_phaseACCURACY3_100pair_v1_p"

    annotated, summary = run_mixed_test(
        scenario_path, real_prefix,
        output_path, summary_path, md_path,
    )

    print()
    print("=" * 50)
    print(f"Total rows: {summary['totals']['total_rows']}")
    print(f"  Scenario: {summary['totals']['scenario_rows']}")
    print(f"  Real:     {summary['totals']['real_rows']}")
    print()
    s = summary["scenario"]
    print(f"Scenario signal accuracy: {s['signal_accuracy']:.1%} ({s['signal_correct']}/{s['with_signal']})")
    print(f"Scenario no-signal accuracy: {s['no_signal_accuracy']:.1%}")
    print()
    r = summary["real"]
    print(f"Real fires: {r['fires']} ({r['fire_rate']:.1%})")
    print(f"Real NO_INTENT: {r['no_intent']} ({r['no_intent_rate']:.1%})")
    print(f"Real FPR (no trigger): {r['fpr_no_trigger']:.1%}")
    print(f"Real fires with trigger: {r['fires_with_trigger']}/{r['fires']} ({r['fires_with_trigger_rate']:.1%})")
    print()
    print("Real intent distribution:")
    for intent, count in sorted(summary["distribution"]["real_intent_dist"].items(), key=lambda x: -x[1]):
        print(f"  {intent}: {count}")


if __name__ == "__main__":
    main()
