#!/usr/bin/env python3
"""
Phase 6.3.8d.1 — Causal Action Audit (Phase B)

This tool reads the paired repaired audit artifacts
produced by
``analyze_doubles_narrow_ally_heal_paired_repair.py``
and reconstructs the per-turn ON selected action and
the OFF counterfactual action for every turn where
a narrow wrong-side candidate was generated.

Definitions (per the Phase 6.3.8d.1 task spec):

- A "real wrong-side selection" is strictly:
    move in {healpulse, floralhealing, decorate}
    AND selected target is an opponent
    AND selected action is legal
    AND selected action is semantically ally-beneficial
- "Generated wrong-side candidates" are rows in the
  audit's ``narrow_ally_heal_candidates`` list with
  ``target_side == "opponent"``. They may or may not
  have been selected.
- "Final wrong-side selections" are the rows above
  whose ``selected`` flag is True.
- "Prevented final wrong-side selections" are ON-side
  blocked rows (since the block score is 0.0 the engine
  never selects a blocked action).

Per-slot records emitted for every turn with a
narrow wrong-side candidate:

  pair_id, arm, battle_tag, turn, slot,
  active_species,
  candidate_move_id, candidate_target_position,
  candidate_target_species, candidate_target_side,
  intended_side,
  blocked_reason,
  raw_candidate_score,
  on_selected_action,
  off_counterfactual_action,
  safe_alternative_action, safe_alternative_score,
  only_legal,
  action_changed,
  joint_action_changed

Accounting validation (Phase B final gate):

  candidate_blocked == selected + avoided
  selected and avoided are mutually exclusive

Artifacts written:

  logs/narrow_ally_heal_paired_phase638d1_causal_audit.jsonl
  logs/narrow_ally_heal_paired_phase638d1_causal_audit.md
  logs/narrow_ally_heal_paired_phase638d1_causal_audit_summary.json
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


# ----- normalization helpers -----


def _norm_action_key(move_id, target_position):
    """Normalize an action key for comparison.

    The same action may appear in different orderings
    (e.g., "switch x" vs "move y"), so we always
    compare on (move_id, target_position).
    """
    return f"{move_id}|{target_position}"


def _joint_action_key(first_order, second_order):
    f = (
        _norm_action_key(
            getattr(getattr(first_order, "order", None), "id", ""),
            getattr(first_order, "move_target", None),
        )
        if first_order
        else ""
    )
    s = (
        _norm_action_key(
            getattr(getattr(second_order, "order", None), "id", ""),
            getattr(second_order, "move_target", None),
        )
        if second_order
        else ""
    )
    return f"{f}||{s}"


def _read_jsonl(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _load_merged_battles(paired_analysis_path):
    """Load the merged Phase 6.3.8d.1 paired battle
    records (the canonical 100-pair / 200-battle
    dataset)."""
    return _read_jsonl(paired_analysis_path)


def _action_label_from_audit(audit_path, turn, slot_key):
    """Extract the audit's structured selected action
    for a given turn and slot.

    Falls back to the per-slot audit dict fields if
    the joint-order string is not parseable.
    """
    if not audit_path or not os.path.isfile(audit_path):
        return None
    recs = _read_jsonl(audit_path)
    if not recs:
        return None
    for r in recs:
        for t in r.get("audit_turns", []) or []:
            if t.get("turn") != turn:
                continue
            slot = t.get(slot_key, {}) or {}
            selected = slot.get("narrow_ally_heal_selected", False)
            if not selected:
                return None
            return {
                "move_id": slot.get("narrow_ally_heal_move_id", ""),
                "intended_side": slot.get("narrow_ally_heal_intended_side", ""),
                "actual_side": slot.get("narrow_ally_heal_actual_side", ""),
                "target_position": slot.get("narrow_ally_heal_target_position", None),
                "target_species": slot.get("narrow_ally_heal_target_species", ""),
            }
    return None


def _selected_joint_action(audit_path, turn):
    """Return a per-slot dict of the actual selected
    action for the turn.

    The audit does not directly store the joint
    action as a structured dict, so we reconstruct it
    from the candidate table (``selected`` flag) plus
    the ``top_5_alternatives`` and the
    ``selected_score`` fields.

    Because the candidate table only contains the
    narrow moves, the joint action for a turn where
    no narrow candidate is selected is reconstructed
    by:
      1. Looking at the per-slot narrow audit fields.
      2. If neither slot has a selected narrow
         candidate, falling back to None (i.e., the
         joint action is not a narrow move).
    """
    out = {"slot_0": None, "slot_1": None}
    if not audit_path or not os.path.isfile(audit_path):
        return out
    recs = _read_jsonl(audit_path)
    for r in recs:
        for t in r.get("audit_turns", []) or []:
            if t.get("turn") != turn:
                continue
            for sk in ("slot_0", "slot_1"):
                s = t.get(sk, {}) or {}
                cands = t.get("narrow_ally_heal_candidates", []) or []
                slot_idx = 0 if sk == "slot_0" else 1
                sel_action = None
                for c in cands:
                    if c.get("slot") == slot_idx and c.get("selected"):
                        sel_action = {
                            "move_id": c.get("move_id", ""),
                            "target_position": c.get("target_position", None),
                            "target_side": c.get("target_side", ""),
                            "target_species": c.get("target_species", ""),
                        }
                        break
                if sel_action is None:
                    if s.get("narrow_ally_heal_selected", False):
                        sel_action = {
                            "move_id": s.get("narrow_ally_heal_move_id", ""),
                            "target_position": s.get("narrow_ally_heal_target_position", None),
                            "target_side": s.get("narrow_ally_heal_actual_side", ""),
                            "target_species": s.get("narrow_ally_heal_target_species", ""),
                        }
                out[sk] = sel_action
            return out
    return out


def _parse_joint_order(message):
    """Parse a showdown ``/choose ...`` joint order
    message into per-slot structured actions.

    The message format is:
        /choose <slot0_action>, <slot1_action>

    Each slot action is one of:
        - move <move_id> [target_position] [terastallize]
        - switch <position>

    Returns:
        (slot0_dict, slot1_dict) where each dict has
        keys ``move_id``, ``target_position`` (None
        for switch), and ``kind`` (``move`` / ``switch``
        / ``unknown``).
    """
    out = [None, None]
    if not message or not isinstance(message, str):
        return out
    msg = message.strip()
    if msg.startswith("/choose "):
        msg = msg[len("/choose "):]
    parts = [p.strip() for p in msg.split(",")]
    for slot_idx, part in enumerate(parts[:2]):
        tokens = part.split()
        if not tokens:
            continue
        kind = tokens[0]
        if kind == "move" and len(tokens) >= 2:
            move_id = tokens[1]
            target = None
            for tok in tokens[2:]:
                if tok in ("terastallize",):
                    continue
                try:
                    target = int(tok)
                    break
                except (TypeError, ValueError):
                    continue
            out[slot_idx] = {
                "kind": "move",
                "move_id": move_id,
                "target_position": target,
            }
        elif kind == "switch" and len(tokens) >= 2:
            try:
                pos = int(tokens[1])
            except (TypeError, ValueError):
                pos = None
            out[slot_idx] = {
                "kind": "switch",
                "move_id": "",
                "target_position": pos,
            }
        else:
            out[slot_idx] = {
                "kind": kind,
                "move_id": "",
                "target_position": None,
            }
    return out


def _actual_joint_action(audit_path, turn):
    """Reconstruct the FULL joint action from the
    audit by parsing the ``selected_joint_order``
    string.
    """
    out = {"slot_0": None, "slot_1": None, "raw": ""}
    if not audit_path or not os.path.isfile(audit_path):
        return out
    recs = _read_jsonl(audit_path)
    for r in recs:
        for t in r.get("audit_turns", []) or []:
            if t.get("turn") != turn:
                continue
            out["raw"] = t.get("selected_joint_order", "")
            s0, s1 = _parse_joint_order(out["raw"])
            out["slot_0"] = s0
            out["slot_1"] = s1
            return out
    return out


# ----- per-slot reconstruction -----


def _record_turn(
    pair_id,
    arm,
    battle_tag,
    on_audit_path,
    off_audit_path,
):
    """Emit per-slot causal-audit records for every turn
    in the ON/OFF audit files that has a narrow
    wrong-side candidate in this arm.

    Returns:
        (records, summary) where records is the list
        of per-slot dicts and summary aggregates the
        accounting invariants.
    """
    records = []
    summary = {
        "candidate_blocked_total": 0,
        "selected_total": 0,
        "avoided_total": 0,
        "mutual_exclusion_fail_total": 0,
        "accounting_fail_total": 0,
        "action_changed_total": 0,
        "joint_action_changed_total": 0,
    }
    audit_path = on_audit_path if arm == "ON" else off_audit_path
    if not audit_path or not os.path.isfile(audit_path):
        return records, summary
    recs = _read_jsonl(audit_path)
    for r in recs:
        for t in r.get("audit_turns", []) or []:
            turn = t.get("turn")
            cands = t.get("narrow_ally_heal_candidates", []) or []
            for c in cands:
                if c.get("target_side") != "opponent":
                    continue
                mid = c.get("move_id", "")
                if mid not in {
                    "healpulse", "floralhealing", "decorate"
                }:
                    continue
                slot_idx = c.get("slot")
                if slot_idx is None:
                    continue
                sk = f"slot_{slot_idx}"
                slot = t.get(sk, {}) or {}
                blocked = bool(
                    c.get("blocked", False)
                    or slot.get(
                        "narrow_ally_heal_candidate_blocked", False
                    )
                )
                selected = bool(
                    c.get("selected", False)
                    or slot.get(
                        "narrow_ally_heal_selected", False
                    )
                )
                avoided = bool(
                    slot.get("narrow_ally_heal_avoided", False)
                )
                only_legal = bool(
                    slot.get("narrow_ally_heal_only_legal", False)
                )
                if blocked and selected and avoided:
                    summary["mutual_exclusion_fail_total"] += 1
                if blocked and not (selected or avoided):
                    summary["accounting_fail_total"] += 1
                if blocked:
                    summary["candidate_blocked_total"] += 1
                    if selected:
                        summary["selected_total"] += 1
                    if avoided:
                        summary["avoided_total"] += 1

                active_mon = (
                    t.get("our_active", []) or []
                )
                active_species = ""
                if slot_idx < len(active_mon):
                    m = active_mon[slot_idx] or {}
                    active_species = m.get("species", "")

                on_sel = _actual_joint_action(on_audit_path, turn)
                off_sel = _actual_joint_action(off_audit_path, turn)
                on_slot_action = on_sel.get(sk)
                off_slot_action = off_sel.get(sk)
                on_joint = (
                    on_sel.get("slot_0"),
                    on_sel.get("slot_1"),
                )
                off_joint = (
                    off_sel.get("slot_0"),
                    off_sel.get("slot_1"),
                )

                on_action_label = None
                if on_slot_action:
                    on_action_label = _norm_action_key(
                        on_slot_action.get("move_id", ""),
                        on_slot_action.get("target_position", None),
                    )
                off_action_label = None
                if off_slot_action:
                    off_action_label = _norm_action_key(
                        off_slot_action.get("move_id", ""),
                        off_slot_action.get("target_position", None),
                    )

                action_changed = (
                    on_action_label is not None
                    and off_action_label is not None
                    and on_action_label != off_action_label
                )
                joint_action_changed = (
                    on_joint != off_joint
                )

                on_raw = on_sel.get("raw", "")
                off_raw = off_sel.get("raw", "")
                if (
                    on_raw
                    and off_raw
                    and on_raw == off_raw
                ):
                    action_changed = False
                    joint_action_changed = False

                safe_alternative = None
                safe_alternative_score = None
                # The OFF counterfactual action is the
                # safe alternative: it's the action
                # the engine would have selected if the
                # narrow rule was not applied.
                if off_slot_action:
                    safe_alternative = _norm_action_key(
                        off_slot_action.get("move_id", ""),
                        off_slot_action.get("target_position", None),
                    )
                    safe_alternative_score = (
                        t.get("selected_score", None)
                    )
                # Fall back: parse the top-1 alternative
                # joint order to find a non-narrow
                # per-slot action.
                if safe_alternative is None:
                    top5 = t.get("top_5_alternatives", []) or []
                    for alt in top5:
                        if not isinstance(alt, str):
                            continue
                        s0_alt, s1_alt = _parse_joint_order(alt)
                        alt_action = (
                            s0_alt if slot_idx == 0 else s1_alt
                        )
                        if alt_action and alt_action.get(
                            "move_id", ""
                        ) and alt_action.get("move_id") != mid:
                            safe_alternative = _norm_action_key(
                                alt_action.get("move_id", ""),
                                alt_action.get("target_position", None),
                            )
                            safe_alternative_score = (
                                t.get("selected_score", None)
                            )
                            break
                # Final fallback: any other selected
                # action at this slot (the joint order
                # is the best non-narrow action).
                if safe_alternative is None and on_slot_action:
                    safe_alternative = _norm_action_key(
                        on_slot_action.get("move_id", ""),
                        on_slot_action.get("target_position", None),
                    )
                    safe_alternative_score = (
                        t.get("selected_score", None)
                    )

                records.append({
                    "pair_id": pair_id,
                    "arm": arm,
                    "battle_tag": battle_tag,
                    "turn": turn,
                    "slot": slot_idx,
                    "active_species": active_species,
                    "candidate_move_id": mid,
                    "candidate_target_position": c.get(
                        "target_position"
                    ),
                    "candidate_target_species": c.get(
                        "target_species", ""
                    ),
                    "candidate_target_side": c.get(
                        "target_side", ""
                    ),
                    "intended_side": "ally",
                    "blocked_reason": c.get(
                        "block_reason", ""
                    ) or slot.get("narrow_ally_heal_reason", ""),
                    "raw_candidate_score": c.get("score", None),
                    "on_selected_action": on_action_label,
                    "off_counterfactual_action": off_action_label,
                    "safe_alternative_action": safe_alternative,
                    "safe_alternative_score": safe_alternative_score,
                    "only_legal": only_legal,
                    "action_changed": action_changed,
                    "joint_action_changed": joint_action_changed,
                    "blocked": blocked,
                    "selected": selected,
                    "avoided": avoided,
                })
                if action_changed:
                    summary["action_changed_total"] += 1
                if joint_action_changed:
                    summary["joint_action_changed_total"] += 1
    return records, summary


def run_causal_audit(paired_jsonl_path, out_dir):
    """Run the Phase B causal action audit."""
    battles = _load_merged_battles(paired_jsonl_path)
    if not battles:
        raise RuntimeError(
            f"No merged battles loaded from {paired_jsonl_path}"
        )

    by_pair = defaultdict(dict)
    for b in battles:
        by_pair[b["pair_id"]][b["side_swap"]] = b

    all_records = []
    aggregate = {
        "generated_wrong_side_total": 0,
        "final_wrong_side_selected_total": 0,
        "prevented_wrong_side_total": 0,
        "action_changes_with_off_mistake": 0,
        "action_changes_without_off_mistake": 0,
        "mutual_exclusion_fail_total": 0,
        "accounting_fail_total": 0,
        "joint_action_changed_total": 0,
        "by_arm": {"ON": {}, "OFF": {}},
    }
    pair_summaries = []

    for pid in sorted(by_pair.keys()):
        for ss in ("D1", "D2"):
            battle = by_pair[pid][ss]
            p1_arm = battle["p1_arm"]
            on_player_is_p1 = battle["on_player_is_p1"]
            on_audit_path = (
                battle["p1_audit_path"] if on_player_is_p1
                else battle["p2_audit_path"]
            )
            off_audit_path = (
                battle["p2_audit_path"] if on_player_is_p1
                else battle["p1_audit_path"]
            )
            on_arm = "ON"
            off_arm = "OFF"
            battle_tag = battle.get("battle_tag", "")

            on_records, on_summary = _record_turn(
                pid, on_arm, battle_tag,
                on_audit_path, off_audit_path,
            )
            off_records, off_summary = _record_turn(
                pid, off_arm, battle_tag,
                on_audit_path, off_audit_path,
            )
            on_recs = on_records
            off_recs = off_records
            on_sum = on_summary
            off_sum = off_summary

            pair_summary = {
                "pair_id": pid,
                "side_swap": ss,
                "on_generated": len(on_recs),
                "on_blocked": on_sum["candidate_blocked_total"],
                "on_selected_wrong_side": on_sum["selected_total"],
                "on_avoided": on_sum["avoided_total"],
                "off_generated": len(off_recs),
                "off_blocked": off_sum["candidate_blocked_total"],
                "off_selected_wrong_side": off_sum["selected_total"],
                "off_avoided": off_sum["avoided_total"],
                "mutual_exclusion_fail": (
                    on_sum["mutual_exclusion_fail_total"]
                    + off_sum["mutual_exclusion_fail_total"]
                ),
                "accounting_fail": (
                    on_sum["accounting_fail_total"]
                    + off_sum["accounting_fail_total"]
                ),
                "action_changed_count": (
                    on_sum["action_changed_total"]
                    + off_sum["action_changed_total"]
                ),
                "joint_action_changed_count": (
                    on_sum["joint_action_changed_total"]
                    + off_sum["joint_action_changed_total"]
                ),
            }
            pair_summaries.append(pair_summary)
            all_records.extend(on_recs)
            all_records.extend(off_recs)

            aggregate["generated_wrong_side_total"] += (
                len(on_recs) + len(off_recs)
            )
            aggregate["final_wrong_side_selected_total"] += (
                on_sum["selected_total"]
                + off_sum["selected_total"]
            )
            aggregate["prevented_wrong_side_total"] += (
                on_sum["candidate_blocked_total"]
            )
            aggregate["mutual_exclusion_fail_total"] += (
                on_sum["mutual_exclusion_fail_total"]
                + off_sum["mutual_exclusion_fail_total"]
            )
            aggregate["accounting_fail_total"] += (
                on_sum["accounting_fail_total"]
                + off_sum["accounting_fail_total"]
            )
            aggregate["joint_action_changed_total"] += (
                on_sum["joint_action_changed_total"]
                + off_sum["joint_action_changed_total"]
            )
            if off_sum["selected_total"] > 0:
                aggregate["action_changes_with_off_mistake"] += (
                    on_sum["action_changed_total"]
                )
            else:
                aggregate["action_changes_without_off_mistake"] += (
                    on_sum["action_changed_total"]
                )
            aggregate["by_arm"]["ON"]["generated"] = (
                aggregate["by_arm"]["ON"].get("generated", 0) + len(on_recs)
            )
            aggregate["by_arm"]["ON"]["selected_wrong_side"] = (
                aggregate["by_arm"]["ON"].get(
                    "selected_wrong_side", 0
                )
                + on_sum["selected_total"]
            )
            aggregate["by_arm"]["ON"]["blocked"] = (
                aggregate["by_arm"]["ON"].get("blocked", 0)
                + on_sum["candidate_blocked_total"]
            )
            aggregate["by_arm"]["ON"]["action_changed"] = (
                aggregate["by_arm"]["ON"].get("action_changed", 0)
                + on_sum["action_changed_total"]
            )
            aggregate["by_arm"]["OFF"]["generated"] = (
                aggregate["by_arm"]["OFF"].get("generated", 0)
                + len(off_recs)
            )
            aggregate["by_arm"]["OFF"]["selected_wrong_side"] = (
                aggregate["by_arm"]["OFF"].get(
                    "selected_wrong_side", 0
                )
                + off_sum["selected_total"]
            )
            aggregate["by_arm"]["OFF"]["blocked"] = (
                aggregate["by_arm"]["OFF"].get("blocked", 0)
                + off_sum["candidate_blocked_total"]
            )
            aggregate["by_arm"]["OFF"]["action_changed"] = (
                aggregate["by_arm"]["OFF"].get("action_changed", 0)
                + off_sum["action_changed_total"]
            )

    os.makedirs(out_dir, exist_ok=True)
    jsonl_out = os.path.join(
        out_dir,
        "narrow_ally_heal_paired_phase638d1_causal_audit.jsonl",
    )
    with open(jsonl_out, "w") as f:
        for rec in all_records:
            f.write(json.dumps(rec) + "\n")

    summary_out = os.path.join(
        out_dir,
        "narrow_ally_heal_paired_phase638d1_causal_audit_summary.json",
    )
    with open(summary_out, "w") as f:
        json.dump(
            {
                "aggregate": aggregate,
                "pair_summaries": pair_summaries,
            },
            f,
            indent=2,
        )

    md_out = os.path.join(
        out_dir,
        "narrow_ally_heal_paired_phase638d1_causal_audit.md",
    )
    with open(md_out, "w") as f:
        f.write(
            "# Phase 6.3.8d.1 — Causal Action Audit\n\n"
        )
        f.write(
            "Inputs: the 100-pair / 200-battle Phase "
            "6.3.8d.1 repaired dataset and the per-side "
            "audit JSONL files. The audit reconstructs "
            "the ON selected action and the OFF "
            "counterfactual action for every turn with "
            "a narrow wrong-side candidate.\n\n"
        )
        f.write("## Aggregate\n\n")
        for k, v in aggregate.items():
            if k == "by_arm":
                f.write(f"- {k}:\n")
                for arm, fields in v.items():
                    f.write(f"  - {arm}: {fields}\n")
            else:
                f.write(f"- {k}: {v}\n")
        f.write("\n## Per-pair / per-side-swap\n\n")
        f.write(
            "| pair | side | on_gen | on_blk | on_sel | on_avoid | "
            "off_gen | off_blk | off_sel | off_avoid | "
            "act_chg | jnt_chg |\n"
        )
        f.write(
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        for ps in pair_summaries:
            f.write(
                f"| {ps['pair_id']} | {ps['side_swap']} | "
                f"{ps['on_generated']} | {ps['on_blocked']} | "
                f"{ps['on_selected_wrong_side']} | "
                f"{ps['on_avoided']} | "
                f"{ps['off_generated']} | {ps['off_blocked']} | "
                f"{ps['off_selected_wrong_side']} | "
                f"{ps['off_avoided']} | "
                f"{ps['action_changed_count']} | "
                f"{ps['joint_action_changed_count']} |\n"
            )
    return aggregate, pair_summaries, all_records


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.3.8d.1 causal action audit"
    )
    parser.add_argument(
        "--paired-jsonl", type=str, required=True,
        help=(
            "Path to the merged Phase 6.3.8d.1 paired "
            "battles JSONL (e.g., logs/"
            "narrow_ally_heal_paired_phase638d1_paired100.jsonl)."
        ),
    )
    parser.add_argument(
        "--out-dir", type=str, default="logs",
        help="Output directory (default: logs).",
    )
    args = parser.parse_args()
    try:
        agg, ps, recs = run_causal_audit(
            args.paired_jsonl, args.out_dir
        )
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}")
        sys.exit(1)
    print(
        f"\nGenerated wrong-side candidates: "
        f"{agg['generated_wrong_side_total']}"
    )
    print(
        f"  ON: {agg['by_arm']['ON'].get('generated', 0)} "
        f"  OFF: {agg['by_arm']['OFF'].get('generated', 0)}"
    )
    print(
        f"Final wrong-side selected: "
        f"{agg['final_wrong_side_selected_total']}"
    )
    print(
        f"  ON: {agg['by_arm']['ON'].get('selected_wrong_side', 0)} "
        f"  OFF: {agg['by_arm']['OFF'].get('selected_wrong_side', 0)}"
    )
    print(
        f"Prevented (ON-side blocked): "
        f"{agg['prevented_wrong_side_total']}"
    )
    print(
        f"Action changes with OFF mistake: "
        f"{agg['action_changes_with_off_mistake']}"
    )
    print(
        f"Action changes without OFF mistake: "
        f"{agg['action_changes_without_off_mistake']}"
    )
    print(
        f"Mutual exclusion fails: "
        f"{agg['mutual_exclusion_fail_total']}"
    )
    print(
        f"Accounting fails: "
        f"{agg['accounting_fail_total']}"
    )


if __name__ == "__main__":
    main()
