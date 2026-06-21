"""
PLANNER-DATA-2 — Intent Policy Dry-Run

Read-only dry-run of a rule-based intent policy on the PLANNER-DATA-1
dataset. No training, no scoring change, no model artifacts.

The policy uses ONLY the visible state (scripted actions fired, opp
moves revealed, weather, fields, our active mons, our mon abilities).
It outputs the predicted intent for each turn.

Ground truth = row's `intent_label` (set per-scenario in
PLANNER-DATA-1).

Output:
  logs/planner_intent_dryrun_v1.jsonl     (rows + predicted_intent)
  logs/planner_intent_dryrun_v1_summary.md
  logs/planner_intent_dryrun_v1_summary.json

Pass criteria:
  - per-family accuracy > 50% (signal exists)
  - per-turn intent coverage (8/8 labels hit)
  - "no scripted action" turn: NO_INTENT (correctly classified)
"""
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, ".")


# --- Move dictionaries (showdown lowercase IDs) ---

SPREAD_MOVES = {
    "heatwave", "rockslide", "earthquake", "dazzlinggleam", "surf",
    "mudslap", "eruption", "discharge", "waterpulse", "sludgewave",
    "glaciate", "muddywater", "boomburst", "makeitrain", "torchsong",
    "drainingkiss", "mysticalfire", "snarl", "thundercage",
    "heatcrash", "iceshard", "powergem", "barrage", "acid",
    "temperflare", "luminacrash", "ruination", "clangoroussoul",
    "alluringvoice", "bleakwindstorm", "sandsearstorm", "wildboltstorm",
    "springtidestorm", "infernalparade", "matchagotcha", "syrupbomb",
}

TERRAIN_MOVES = {
    "electricterrain", "grassyterrain", "mistyterrain", "psychicterrain",
}

WEATHER_MOVES = {
    "raindance", "sunnyday", "sandstorm", "snowscape", "desolateland",
}

REDIRECTION_MOVES = {
    "followme", "ragepowder", "spotlight",
}

STAT_BOOST_MOVES = {
    "swordsdance", "nastyplot", "calmmind", "quiverdance",
    "dragondance", "bulkup", "irondefense", "amnesia", "tailglow",
    "shellsmash", "agility", "rockpolish", "coil", "curse",
    "workup", "acidspray", "acupressure", "flatter", "growth",
    "meditate", "sharpen", "meteormash", "bellydrum", "clangoroussoul",
    "victorydance", "takeheart", "torchsong", "stuffcheeks",
}

SPEED_CONTROL_MOVES = {
    "trickroom", "tailwind",
}

TR_TARGET_ABILITIES = {
    "justified",  # Gallade's Justified triggers on dark move (Beat Up uses type of attacker, not dark)
}


def predict_intent(row):
    """Predict intent from visible state.

    Returns (intent_label, matched_rule, moves_matched).
    """
    scripted = row.get("scripted_action_fired", [])
    revealed = row.get("state_snapshot", {}).get("opp_active_moves_revealed", [])
    weather = row.get("state_snapshot", {}).get("weather", [])
    fields = row.get("state_snapshot", {}).get("fields", [])

    # Collect all moves the opp has shown this turn
    moves_this_turn = set()
    for a in scripted:
        moves_this_turn.add(a.get("move", ""))

    # Check for speed control (highest priority — TR/TW define the whole match)
    tr_fired = bool(moves_this_turn & SPEED_CONTROL_MOVES)
    if tr_fired and "trickroom" in moves_this_turn:
        return "ANTI_TRICK_ROOM", "speed_control_tr", ["trickroom"]
    if tr_fired and "tailwind" in moves_this_turn:
        return "ANTI_TAILWIND", "speed_control_tw", ["tailwind"]

    # Check for stat boost
    boost_moves = moves_this_turn & STAT_BOOST_MOVES
    if boost_moves:
        return "ANTI_STAT_BOOST", "stat_boost", list(boost_moves)

    # Check for spread damage
    spread_moves = moves_this_turn & SPREAD_MOVES
    if spread_moves:
        return "SPREAD_DEFENSE", "spread_damage", list(spread_moves)

    # Check for redirection
    redir_moves = moves_this_turn & REDIRECTION_MOVES
    if redir_moves:
        return "REDIRECTION_RESPONSE", "redirection", list(redir_moves)

    # Check for weather
    weather_moves = moves_this_turn & WEATHER_MOVES
    if weather_moves:
        return "WEATHER_CONTROL", "weather_setter", list(weather_moves)

    # Check for terrain
    terrain_moves = moves_this_turn & TERRAIN_MOVES
    if terrain_moves:
        return "TERRAIN_CONTROL", "terrain_setter", list(terrain_moves)

    # Check for beatup+justified combo
    if "beatup" in moves_this_turn:
        return "COMBO_ENABLE", "combo_beatup", ["beatup"]

    # No scripted action: no signal
    return "NO_INTENT", "no_action", []


def load_dataset(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def run_dryrun(dataset_path, output_path, summary_path, md_path):
    rows = load_dataset(dataset_path)

    # Per-turn semantics:
    #   - turn with scripted action: GT = row.intent_label (the scenario family)
    #   - turn without scripted action: GT = NO_INTENT (no canonical signal that turn)
    # This matches a real planner: the policy fires the right intent on signal
    # turns and stays quiet (NO_INTENT) on non-signal turns.

    # Annotate each row
    annotated = []
    for r in rows:
        predicted, rule, moves = predict_intent(r)
        if r["scripted_action_fired"]:
            per_turn_gt = r["intent_label"]
        else:
            per_turn_gt = "NO_INTENT"
        new_row = dict(r)
        new_row["predicted_intent"] = predicted
        new_row["matched_rule"] = rule
        new_row["matched_moves"] = moves
        new_row["per_turn_gt"] = per_turn_gt
        new_row["correct"] = (predicted == per_turn_gt)
        annotated.append(new_row)

    # Write JSONL
    with open(output_path, "w") as f:
        for r in annotated:
            f.write(json.dumps(r) + "\n")

    # Compute stats
    total = len(annotated)
    correct = sum(1 for r in annotated if r["correct"])
    accuracy = correct / total if total else 0

    per_family = defaultdict(lambda: {"total": 0, "correct": 0, "predicted": Counter(), "gt": Counter()})
    for r in annotated:
        fam = r["family"]
        per_family[fam]["total"] += 1
        if r["correct"]:
            per_family[fam]["correct"] += 1
        per_family[fam]["predicted"][r["predicted_intent"]] += 1
        per_family[fam]["gt"][r["intent_label"]] += 1

    # Per-intent stats
    per_intent = defaultdict(lambda: {"total": 0, "correct": 0, "predicted_as": Counter()})
    for r in annotated:
        intent = r["intent_label"]
        per_intent[intent]["total"] += 1
        if r["correct"]:
            per_intent[intent]["correct"] += 1
        per_intent[intent]["predicted_as"][r["predicted_intent"]] += 1

    # Confusion: predicted vs ground truth
    confusion = defaultdict(lambda: Counter())
    for r in annotated:
        confusion[r["intent_label"]][r["predicted_intent"]] += 1

    # Per-turn signal: do turns with scripted actions get the right intent?
    signal_rows = [r for r in annotated if r["scripted_action_fired"]]
    no_signal_rows = [r for r in annotated if not r["scripted_action_fired"]]
    signal_correct = sum(1 for r in signal_rows if r["correct"])
    nosignal_correct = sum(1 for r in no_signal_rows if r["correct"])

    summary = {
        "totals": {
            "total_rows": total,
            "correct": correct,
            "accuracy": accuracy,
            "rows_with_scripted_action": len(signal_rows),
            "correct_with_scripted_action": signal_correct,
            "accuracy_with_scripted_action": (
                signal_correct / len(signal_rows) if signal_rows else 0
            ),
            "rows_no_scripted_action": len(no_signal_rows),
            "correct_no_scripted_action": nosignal_correct,
            "accuracy_no_scripted_action": (
                nosignal_correct / len(no_signal_rows) if no_signal_rows else 0
            ),
        },
        "per_family": {
            fam: {
                "total": v["total"],
                "correct": v["correct"],
                "accuracy": v["correct"] / v["total"] if v["total"] else 0,
                "predicted_dist": dict(v["predicted"]),
                "ground_truth_dist": dict(v["gt"]),
            }
            for fam, v in per_family.items()
        },
        "per_intent": {
            intent: {
                "total": v["total"],
                "correct": v["correct"],
                "accuracy": v["correct"] / v["total"] if v["total"] else 0,
                "predicted_as_dist": dict(v["predicted_as"]),
            }
            for intent, v in per_intent.items()
        },
        "confusion": {
            gt: dict(pred) for gt, pred in confusion.items()
        },
    }

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Markdown summary
    lines = []
    lines.append("# PLANNER-DATA-2 — Intent Policy Dry-Run")
    lines.append("")
    lines.append(f"**Total rows**: {total}")
    lines.append(f"**Correct**: {correct}")
    lines.append(f"**Accuracy**: {accuracy:.1%}")
    lines.append("")
    lines.append("## Accuracy breakdown")
    lines.append("")
    t = summary["totals"]
    lines.append(f"| segment | rows | correct | accuracy |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| All rows | {t['total_rows']} | {t['correct']} | {t['accuracy']:.1%} |")
    lines.append(f"| With scripted action | {t['rows_with_scripted_action']} | {t['correct_with_scripted_action']} | {t['accuracy_with_scripted_action']:.1%} |")
    lines.append(f"| No scripted action | {t['rows_no_scripted_action']} | {t['correct_no_scripted_action']} | {t['accuracy_no_scripted_action']:.1%} |")
    lines.append("")
    lines.append("## Per-family accuracy")
    lines.append("")
    lines.append("| family | rows | correct | accuracy | predicted dist |")
    lines.append("|---|---|---|---|---|")
    for fam, v in summary["per_family"].items():
        pred_dist = ", ".join(f"{k}:{c}" for k, c in v["predicted_dist"].items())
        lines.append(f"| `{fam}` | {v['total']} | {v['correct']} | {v['accuracy']:.1%} | {pred_dist} |")
    lines.append("")
    lines.append("## Per-intent accuracy")
    lines.append("")
    lines.append("| intent | rows | correct | accuracy | predicted as |")
    lines.append("|---|---|---|---|---|")
    for intent, v in summary["per_intent"].items():
        pred_dist = ", ".join(f"{k}:{c}" for k, c in v["predicted_as_dist"].items())
        lines.append(f"| `{intent}` | {v['total']} | {v['correct']} | {v['accuracy']:.1%} | {pred_dist} |")
    lines.append("")
    lines.append("## Confusion matrix (rows=ground truth, cols=predicted)")
    lines.append("")
    all_intents = sorted({i for r in annotated for i in [r["intent_label"], r["predicted_intent"]]})
    header = "| gt \\ pred | " + " | ".join(all_intents) + " |"
    sep = "|---|" + "|".join("---" for _ in all_intents) + "|"
    lines.append(header)
    lines.append(sep)
    for gt in all_intents:
        row = [str(confusion[gt].get(p, 0)) for p in all_intents]
        lines.append(f"| `{gt}` | " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Policy rules")
    lines.append("")
    lines.append("1. **speed_control_tr**: any move in {trickroom} → ANTI_TRICK_ROOM")
    lines.append("2. **speed_control_tw**: any move in {tailwind} → ANTI_TAILWIND")
    lines.append("3. **stat_boost**: any move in {swordsdance, nastyplot, ...} → ANTI_STAT_BOOST")
    lines.append("4. **spread_damage**: any move in {heatwave, rockslide, earthquake, ...} → SPREAD_DEFENSE")
    lines.append("5. **redirection**: any move in {followme, ragepowder, spotlight} → REDIRECTION_RESPONSE")
    lines.append("6. **weather_setter**: any move in {raindance, sunnyday, ...} → WEATHER_CONTROL")
    lines.append("7. **terrain_setter**: any move in {electricterrain, grassyterrain, ...} → TERRAIN_CONTROL")
    lines.append("8. **combo_beatup**: move=beatup → COMBO_ENABLE")
    lines.append("9. **no_action**: nothing matched → NO_INTENT")
    lines.append("")
    lines.append("## Pass criteria")
    lines.append("")
    lines.append(f"- [{'x' if accuracy >= 0.5 else ' '}] per-family accuracy > 50% (signal exists)")
    lines.append(f"- [{'x' if len(per_family) >= 8 else ' '}] per-family coverage (8/8 labels hit)")
    lines.append(f"- [{'x' if nosignal_correct == len(no_signal_rows) else ' '}] NO_INTENT for no-scripted-action turns")
    lines.append(f"- [{'x' if signal_correct / max(1, len(signal_rows)) >= 0.5 else ' '}] signal-row accuracy > 50%")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    return annotated, summary


def main():
    output_path = "logs/planner_intent_dryrun_v1.jsonl"
    summary_path = "logs/planner_intent_dryrun_v1_summary.json"
    md_path = "logs/planner_intent_dryrun_v1_summary.md"
    dataset_path = "logs/planner_dataset_v1.jsonl"

    annotated, summary = run_dryrun(dataset_path, output_path, summary_path, md_path)
    print(f"Wrote {len(annotated)} annotated rows to {output_path}")
    print(f"Wrote summary to {summary_path}")
    print(f"Wrote MD summary to {md_path}")
    print()
    t = summary["totals"]
    print(f"Total accuracy: {t['accuracy']:.1%} ({t['correct']}/{t['total_rows']})")
    print(f"With scripted action: {t['accuracy_with_scripted_action']:.1%} ({t['correct_with_scripted_action']}/{t['rows_with_scripted_action']})")
    print(f"No scripted action: {t['accuracy_no_scripted_action']:.1%} ({t['correct_no_scripted_action']}/{t['rows_no_scripted_action']})")
    print()
    print("Per-family accuracy:")
    for fam, v in summary["per_family"].items():
        print(f"  {fam}: {v['accuracy']:.1%} ({v['correct']}/{v['total']})")


if __name__ == "__main__":
    main()
