#!/usr/bin/env python3
"""Inspector for Phase 6.4 switch candidate safety cases.

Filters:
  --final-unsafe
  --legal-safer-joint
  --avoided
  --selection-changed
  --unavoidable-assignment
  --eligible-negative-boost
  --offensive-drop
  --defensive-drop
  --speed-drop
  --battle <battle_tag>
  --filepath <jsonl>
"""
import argparse
import json
import os
import sys


def inspect(args):
    if not os.path.exists(args.filepath):
        print(f"Error: File not found: {args.filepath}")
        sys.exit(1)

    results = []

    with open(args.filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                battle_tag = battle.get("battle_tag", "")
                won = battle.get("won", False)

                if args.battle and args.battle not in battle_tag:
                    continue

                for turn in battle.get("audit_turns", []):
                    turn_num = turn.get("turn", 0)

                    for slot_idx, slot_key in enumerate(("slot_0", "slot_1")):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue

                        is_forced = bool(slot.get("forced_switch"))
                        is_final_unsafe = bool(slot.get("final_unsafe_switch_selected"))
                        is_legal_safer = bool(slot.get("legal_safer_joint_switch_available"))
                        is_avoided = bool(slot.get("unsafe_switch_avoided_by_type_safety"))
                        is_selection_changed = bool(slot.get("joint_switch_selection_changed_by_type_safety"))
                        is_unavoidable = bool(slot.get("unavoidable_unsafe_joint_assignment", False))
                        is_eligible_neg = bool(slot.get("negative_boost_decision_eligible"))
                        is_off_drop = bool(slot.get("negative_boost_relevant_offensive_drop"))
                        is_def_drop = bool(slot.get("negative_boost_defensive_drop"))
                        is_spd_drop = bool(slot.get("negative_boost_speed_drop"))
                        is_severe = bool(slot.get("neg_boost_severe_negative_boost"))

                        # Apply filters
                        if args.final_unsafe and not is_final_unsafe:
                            continue
                        if args.legal_safer_joint and not is_legal_safer:
                            continue
                        if args.avoided and not is_avoided:
                            continue
                        if args.selection_changed and not is_selection_changed:
                            continue
                        if args.unavoidable_assignment and not is_unavoidable:
                            continue
                        if args.eligible_negative_boost and not is_eligible_neg:
                            continue
                        if args.offensive_drop and not is_off_drop:
                            continue
                        if args.defensive_drop and not is_def_drop:
                            continue
                        if args.speed_drop and not is_spd_drop:
                            continue
                        if args.severe_negative_boost and not is_severe:
                            continue
                        if args.forced and not is_forced:
                            continue

                        # Check if any filter is active
                        has_filter = (args.final_unsafe or args.legal_safer_joint or
                                      args.avoided or args.selection_changed or
                                      args.unavoidable_assignment or args.eligible_negative_boost or
                                      args.offensive_drop or args.defensive_drop or
                                      args.speed_drop or args.severe_negative_boost or
                                      args.forced)
                        if not has_filter:
                            if not (is_forced or is_final_unsafe or is_legal_safer or
                                    is_avoided or is_selection_changed or is_unavoidable or
                                    is_eligible_neg or is_severe):
                                continue

                        result = {
                            "battle_tag": battle_tag,
                            "turn": turn_num,
                            "slot": slot_idx,
                            "outcome": "win" if won else "loss",
                            "forced_switch": is_forced,
                            "final_unsafe": is_final_unsafe,
                            "legal_safer_joint": is_legal_safer,
                            "avoided": is_avoided,
                            "selection_changed": is_selection_changed,
                            "unavoidable": is_unavoidable,
                            "double_threat": bool(slot.get("final_double_threat_switch_selected")),
                            "switch_species": slot.get("selected_switch_species", ""),
                            "switch_types": slot.get("selected_switch_types", ""),
                            "switch_hp": slot.get("selected_switch_hp_fraction", 1.0),
                            "raw_safety_score": slot.get("selected_switch_raw_safety_score", 0.0),
                            "relative_adjustment": slot.get("selected_switch_relative_adjustment", 0.0),
                            "worst_multiplier": slot.get("selected_switch_worst_multiplier", 1.0),
                            "best_safe_species": slot.get("best_safe_switch_species", ""),
                            "best_safe_score": slot.get("best_safe_switch_score", 0.0),
                            "action": slot.get("action", ""),
                            "eligible_neg_boost": is_eligible_neg,
                            "neg_action_kind": slot.get("negative_boost_selected_action_kind", ""),
                            "neg_switch_count": slot.get("negative_boost_legal_switch_count", 0),
                            "neg_best_switch": slot.get("negative_boost_best_switch_species", ""),
                            "neg_best_sw_score": slot.get("negative_boost_best_switch_score", 0.0),
                            "neg_best_mv_score": slot.get("negative_boost_best_move_score", 0.0),
                            "neg_sw_mv_gap": slot.get("negative_boost_switch_score_gap", 0.0),
                            "neg_off_drop": is_off_drop,
                            "neg_def_drop": is_def_drop,
                            "neg_spd_drop": is_spd_drop,
                            "neg_stages": slot.get("neg_boost_total_negative_stages", 0),
                            "severe_neg": is_severe,
                            "top_alternatives": turn.get("top_5_alternatives", []),
                            "top_scores": turn.get("top_5_scores", []),
                        }
                        results.append(result)
            except Exception:
                continue

    if not results:
        print("No matching cases found.")
        return

    print(f"Found {len(results)} matching case(s):\n")
    for idx, r in enumerate(results, 1):
        tags = []
        if r["forced_switch"]:
            tags.append("FORCED")
        if r["final_unsafe"]:
            tags.append("UNSAFE")
        if r["avoided"]:
            tags.append("AVOIDED")
        if r["legal_safer_joint"]:
            tags.append("LEGAL_SAFER")
        if r["selection_changed"]:
            tags.append("CHANGED")
        if r["unavoidable"]:
            tags.append("UNAVOIDABLE")
        if r["double_threat"]:
            tags.append("DOUBLE_THREAT")
        if r["eligible_neg_boost"]:
            tags.append("NEG_ELIGIBLE")
        if r["severe_neg"]:
            tags.append(f"SEVERE_NEG({r['neg_stages']})")
        tag_str = " | ".join(tags) if tags else "NONE"

        print(f"  {idx}. Battle: {r['battle_tag']} Turn: {r['turn']} Slot: {r['slot']} ({r['outcome']})")
        print(f"     Tags: {tag_str}")
        print(f"     Action: {r['action']}")
        if r["switch_species"]:
            print(f"     Switch: {r['switch_species']} ({r['switch_types']}) HP={r['switch_hp']:.2f}")
            print(f"     Safety: raw={r['raw_safety_score']:.1f} adj={r['relative_adjustment']:.1f} worst_mult={r['worst_multiplier']:.2f}")
        if r["best_safe_species"]:
            print(f"     Best Safe: {r['best_safe_species']} (score={r['best_safe_score']:.1f})")
        if r["eligible_neg_boost"]:
            print(f"     NegBoost: kind={r['neg_action_kind']} switches={r['neg_switch_count']} best_sw={r['neg_best_switch']}({r['neg_best_sw_score']:.1f}) best_mv={r['neg_best_mv_score']:.1f} gap={r['neg_sw_mv_gap']:.1f}")
            drops = []
            if r["neg_off_drop"]:
                drops.append("OFF")
            if r["neg_def_drop"]:
                drops.append("DEF")
            if r["neg_spd_drop"]:
                drops.append("SPD")
            if drops:
                print(f"     Drops: {', '.join(drops)}")
        if r["top_alternatives"]:
            print(f"     Top Alternatives:")
            for ai, (alt, sc) in enumerate(zip(r["top_alternatives"][:3], r["top_scores"][:3]), 1):
                print(f"       {ai}. {alt} (score={sc:.1f})")
        print()


def main():
    parser = argparse.ArgumentParser(description="Inspect switch candidate safety cases")
    parser.add_argument("--final-unsafe", action="store_true", help="Show cases where final unsafe switch was selected")
    parser.add_argument("--legal-safer-joint", action="store_true", help="Show cases where legal safer joint switch was available")
    parser.add_argument("--avoided", action="store_true", help="Show cases where type-safety avoided unsafe switch")
    parser.add_argument("--selection-changed", action="store_true", help="Show cases where joint selection changed")
    parser.add_argument("--unavoidable-assignment", action="store_true", help="Show unavoidable unsafe joint assignments")
    parser.add_argument("--eligible-negative-boost", action="store_true", help="Show eligible negative-boost decisions")
    parser.add_argument("--offensive-drop", action="store_true", help="Show cases with offensive drops")
    parser.add_argument("--defensive-drop", action="store_true", help="Show cases with defensive drops")
    parser.add_argument("--speed-drop", action="store_true", help="Show cases with speed drops")
    parser.add_argument("--forced", action="store_true", help="Show forced switch cases")
    parser.add_argument("--severe-negative-boost", action="store_true", help="Show severe negative-boost cases")
    parser.add_argument("--battle", type=str, default=None, help="Filter by battle tag (substring match)")
    parser.add_argument("--filepath", type=str, default="logs/doubles_decision_audit.jsonl", help="Path to JSONL audit log")
    args = parser.parse_args()
    inspect(args)


if __name__ == "__main__":
    main()
