#!/usr/bin/env python3
"""Phase 6.4.8 — Disabled Safety Feature Failure Attribution Inspector.

Unified inspector for forced-switch, stale-target, and stat-drop safety cases.
Reads JSONL audit logs and summarizes candidate/selected cases.
"""
import json, os, argparse, sys

FEATURE_MAP = {
    "forced-switch": "forced_switch",
    "stale-target": "stale_target",
    "stat-drop": "stat_drop_switch",
}


def _get_feature_cases(turn_data, feature):
    cases = []
    if feature == "stale_target":
        if turn_data.get("stale_target_selected") or turn_data.get("stale_target_avoided"):
            cases.append({
                "feature": "stale-target",
                "selected": turn_data.get("stale_target_selected", False),
                "avoided": turn_data.get("stale_target_avoided", False),
                "reason": turn_data.get("stale_target_reason", ""),
                "type_immune": turn_data.get("stale_target_caused_type_immune", False),
                "no_effect": turn_data.get("stale_target_caused_no_effect", False),
                "first_move": turn_data.get("stale_target_first_move", ""),
                "first_target": turn_data.get("stale_target_first_target", ""),
                "second_move": turn_data.get("stale_target_second_move", ""),
                "second_target": turn_data.get("stale_target_second_intended_target", ""),
                "fallback": turn_data.get("stale_target_fallback_target", ""),
                "slot": "turn",
            })
    else:
        for sk in ("slot_0", "slot_1"):
            slot = turn_data.get(sk, {})
            if not slot:
                continue
            if feature == "forced_switch" and slot.get("forced_switch"):
                bad = (slot.get("forced_switch_selected_double_threat")
                       or slot.get("forced_switch_selected_quad_weak")
                       or slot.get("forced_switch_selected_low_hp"))
                changed = slot.get("forced_switch_safety_selection_changed", False)
                cases.append({
                    "feature": "forced-switch",
                    "slot": sk,
                    "selected": True,
                    "avoided": False,
                    "selection_changed": changed,
                    "bad_outcome": bad,
                    "double_threat": slot.get("forced_switch_selected_double_threat", False),
                    "quad_weak": slot.get("forced_switch_selected_quad_weak", False),
                    "low_hp": slot.get("forced_switch_selected_low_hp", False),
                    "reason": slot.get("forced_switch_reason", ""),
                    "best_safety_species": slot.get("forced_switch_best_safety_species", ""),
                    "sel_safety_score": slot.get("forced_switch_selected_safety_score", 0),
                    "best_safety_score": slot.get("forced_switch_best_safety_score", 0),
                    "candidate_count": slot.get("forced_switch_candidate_count", 0),
                    "fallback_used": slot.get("forced_switch_order_fallback_used", False),
                    "selected_species": slot.get("forced_switch_selected_species", ""),
                })
            if feature == "stat_drop_switch" and slot.get("stat_drop_switch_pressure_active"):
                bad = slot.get("stat_drop_switch_stayed_unproductive", False)
                changed = slot.get("stat_drop_switch_selection_changed", False)
                cases.append({
                    "feature": "stat-drop",
                    "slot": sk,
                    "selected": slot.get("stat_drop_switch_selected", False),
                    "avoided": False,
                    "selection_changed": changed,
                    "bad_outcome": bad,
                    "stayed_productive": slot.get("stat_drop_switch_stayed_productive", False),
                    "stayed_unproductive": slot.get("stat_drop_switch_stayed_unproductive", False),
                    "categories": slot.get("stat_drop_switch_pressure_categories", []),
                    "reason": slot.get("stat_drop_switch_reason", ""),
                    "best_switch": slot.get("stat_drop_switch_best_switch_species", ""),
                    "best_switch_score": slot.get("stat_drop_switch_best_switch_score", 0),
                    "best_non_switch": slot.get("stat_drop_switch_best_non_switch_score", 0),
                    "pressure_score": slot.get("stat_drop_switch_pressure_score", 0),
                })
    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Unified Disabled Safety Feature Inspector"
    )
    parser.add_argument("--filepath", type=str, nargs="+",
                        default=["logs/doubles_decision_audit.jsonl"])
    parser.add_argument("--feature", type=str, default="all",
                        choices=["forced-switch", "stale-target", "stat-drop", "all"])
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--bad-outcome-only", action="store_true")
    parser.add_argument("--battle", type=str)
    parser.add_argument("--turn", type=int, default=None)
    parser.add_argument("--losses-only", action="store_true")
    parser.add_argument("--wins-only", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    features = ["forced_switch", "stale_target", "stat_drop_switch"]
    if args.feature != "all":
        features = [FEATURE_MAP[args.feature]]

    matched = []
    for fp in args.filepath:
        if not os.path.exists(fp):
            print(f"Warning: {fp} not found")
            continue
        with open(fp) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                bt = rec.get("battle_tag", "Unknown")
                if args.battle and args.battle != bt:
                    continue
                won = rec.get("won", False)
                if args.losses_only and won:
                    continue
                if args.wins_only and not won:
                    continue
                for td in rec.get("audit_turns", []):
                    turn = td.get("turn", 0)
                    if args.turn is not None and turn != args.turn:
                        continue
                    for feat in features:
                        cases = _get_feature_cases(td, feat)
                        for c in cases:
                            if args.changed_only and not c.get("selection_changed"):
                                continue
                            if args.bad_outcome_only and not c.get("bad_outcome"):
                                continue
                            c["battle_tag"] = bt
                            c["turn"] = turn
                            c["won"] = won
                            c["selected_order"] = td.get("selected_joint_order", "")[:70]
                            c["score_gap"] = td.get("score_gap_selected_best_alt", 0)
                            matched.append(c)

    if not matched:
        print("No matching cases found.")
        return

    wins = sum(1 for c in matched if c["won"])
    losses = sum(1 for c in matched if not c["won"])
    print(f"Found {len(matched)} cases ({wins}W/{losses}L)")
    print()

    for i, c in enumerate(matched[:args.limit], 1):
        print(f"Case #{i}:")
        print(f"  Feature      : {c['feature']}")
        print(f"  Battle       : {c['battle_tag']}")
        print(f"  Turn         : {c['turn']}")
        print(f"  Outcome      : {'WIN' if c['won'] else 'LOSS'}")
        print(f"  Selected     : {c['selected_order']}")
        if c["feature"] == "stale-target":
            print(f"  Selected?    : {c['selected']}  Avoided? : {c['avoided']}")
            print(f"  Type-Immune? : {c['type_immune']}  No-Effect? : {c['no_effect']}")
            print(f"  First Move   : {c['first_move']} -> {c['first_target']}")
            print(f"  Second Move  : {c['second_move']} -> {c['second_target']}")
            print(f"  Fallback     : {c['fallback']}")
        elif c["feature"] == "forced-switch":
            print(f"  Slot         : {c['slot']}")
            print(f"  DT:{c['double_threat']} QW:{c['quad_weak']} LowHP:{c['low_hp']}")
            print(f"  Changed?     : {c['selection_changed']}")
            print(f"  Selected     : {c['selected_species']}")
            print(f"  Best Safe    : {c['best_safety_species']}")
            print(f"  Safety Score : {c['sel_safety_score']:.1f} / {c['best_safety_score']:.1f}")
            print(f"  Candidates   : {c['candidate_count']}")
        elif c["feature"] == "stat-drop":
            print(f"  Slot         : {c['slot']}")
            print(f"  Categories   : {c['categories']}")
            print(f"  Switch Sel?  : {c['selected']}  Stayed Unprod? : {c['stayed_unproductive']}")
            print(f"  Changed?     : {c['selection_changed']}")
            print(f"  Best Switch  : {c['best_switch']} ({c['best_switch_score']:.1f})")
            print(f"  Best Non-Sw  : {c['best_non_switch']:.1f}  Pressure: {c['pressure_score']:.1f}")
        print(f"  Reason       : {c['reason']}")
        print(f"  Score Gap    : {c['score_gap']:.2f}")
        print()


if __name__ == "__main__":
    main()
