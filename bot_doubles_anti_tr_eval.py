"""PLANNER-ANTI-TR-EVAL-1: paired eval harness.

Runs paired ON vs OFF battles and computes metrics.

Design: PLANNER-ANTI-TR-EVAL-1 (logs/phasePLANNER_ANTI_TR_EVAL_1.md)
"""
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/phurin/Program/Showdown_AI/pokemon-showdown-ai")

import bot_doubles_planner_spread_smoke as smoke
from bot_doubles_tr_user import DoublesTRUserPlayer

smoke.DoublesBasicAwarePlayer = DoublesTRUserPlayer

original_make_config = smoke._make_config

WG_TEAM = "data/curated_teams/custom/planner_anti_tr_wg_team.json"
OPP_TEAM = "data/curated_teams/custom/general_opp_tr.json"

ARTIFACT_DIR = Path("logs")

# Module-level state to control anti-TR per call
_eval_state = {"anti_tr": False}


def make_eval_config(enable_intent, enable_spread):
    cfg = original_make_config(enable_intent, enable_spread)
    cfg.enable_anti_trick_room_response = _eval_state["anti_tr"]
    cfg.anti_trick_room_response_bonus = 500.0
    cfg.anti_trick_room_ko_bonus = 200.0
    return cfg


smoke._make_config = make_eval_config


def classify_response(our_order, intent, opp_species):
    """Classify a single response move.

    Returns one of:
      - NOT_ANTI_TR (intent was not ANTI_TR)
      - TAUNT (Taunt/Encore/Disable on opp slot, target=setter slot)
      - WRONG_TARGET_TAUNT
      - FAKE_OUT
      - KO_SETTER (damaging move on setter)
      - DAMAGE_OTHER (damaging on non-setter)
      - SPREAD_DAMAGE (multi-target)
      - OTHER_SUPPORT (Protect, switch, etc.)
    """
    if intent != "ANTI_TRICK_ROOM":
        return "NOT_ANTI_TR"
    if not hasattr(our_order, "order") or our_order.order is None:
        return "OTHER_SUPPORT"
    move_id = str(getattr(our_order.order, "id", "")).lower().replace(" ", "").replace("-", "").replace("_", "")
    target = getattr(our_order, "move_target", None)
    bp = getattr(our_order.order, "base_power", 0) or 0

    if move_id in ("taunt", "encore", "disable"):
        return "TAUNT" if target in (1, 2) else "WRONG_TARGET_TAUNT"
    if move_id == "fakeout":
        return "FAKE_OUT"
    if bp > 0:
        # Determine if target is the setter
        if target == 1:
            return "KO_SETTER" if opp_species[0] in TR_SETTERS else "DAMAGE_OTHER"
        elif target == 2:
            return "KO_SETTER" if len(opp_species) > 1 and opp_species[1] in TR_SETTERS else "DAMAGE_OTHER"
        else:
            return "SPREAD_DAMAGE"
    return "OTHER_SUPPORT"


# Common TR setters in VGC 2026
TR_SETTERS = {"hatterene", "farigiraf", "indeedee", "whimsicott", "gardevoir", "porygon2"}


DAMAGE_MOVES = {
    "flareblitz", "saltcure", "earthquake", "ironhead", "kowtowcleave",
    "extremespeed", "rockslide", "crunch", "thunderpunch", "bugbuzz",
    "moonblast", "psychic", "shadowball", "heatwave", "scaleshot",
}


def classify_joint_order(sel: str) -> str:
    """Simple string-based classifier for joint order response class."""
    s = sel.lower()
    has_taunt = any(m in s for m in ("taunt", "encore", "disable"))
    has_fakeout = "fakeout" in s
    has_protect = "protect" in s
    has_damage = any(m in s for m in DAMAGE_MOVES)
    is_switch_pass = (
        s.startswith("/choose switch") or ", switch" in s
        or " pass" in s or s.endswith("pass")
    )
    if has_taunt:
        return "TAUNT"
    if has_fakeout:
        return "FAKE_OUT"
    if has_protect:
        return "PROTECT"
    if is_switch_pass:
        return "PASS_SWITCH"
    if has_damage:
        return "DAMAGE"
    return "OTHER"


def compute_metrics(audit_path: Path) -> dict:
    """Compute per-pair metrics from audit JSONL."""
    metrics = {
        "won": False,
        "turns": 0,
        "anti_tr_turns": 0,
        "taunt_count": 0,
        "ko_setter_count": 0,
        "fake_out_count": 0,
        "protect_count": 0,
        "pass_switch_count": 0,
        "ignore_count": 0,
        "other_count": 0,
        "wrong_target_taunt": 0,
        "tr_set_count": 0,
        "tr_prevented": True,
        "spam_violation": 0,
        "selected_class_top3": [],
    }
    classes = []
    last_turn = 0
    for line in audit_path.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("won"):
            metrics["won"] = True
        for turn in rec.get("audit_turns", []):
            t = turn.get("turn", 0)
            last_turn = max(last_turn, t)
            state = turn.get("state_snapshot", {}) or {}
            intent = state.get("planner_intent_label")
            sel = turn.get("selected_joint_order", "")
            fields = state.get("fields", [])

            if intent == "ANTI_TRICK_ROOM":
                metrics["anti_tr_turns"] += 1
                cls = classify_joint_order(sel)
                classes.append(cls)
                if cls == "TAUNT":
                    metrics["taunt_count"] += 1
                elif cls == "FAKE_OUT":
                    metrics["fake_out_count"] += 1
                elif cls == "PROTECT":
                    metrics["protect_count"] += 1
                elif cls == "PASS_SWITCH":
                    metrics["pass_switch_count"] += 1
                elif cls == "DAMAGE":
                    # Without target parsing, count as KO candidate
                    metrics["ko_setter_count"] += 1
                else:
                    metrics["other_count"] += 1

            if "trickroom" in str(fields).lower() or "trick_room" in str(fields).lower():
                metrics["tr_set_count"] += 1
                metrics["tr_prevented"] = False

            if turn.get("planner_anti_tr_spam_violation"):
                metrics["spam_violation"] += 1

        metrics["turns"] = last_turn

    counter = Counter(classes)
    metrics["selected_class_top3"] = counter.most_common(3)
    return metrics


async def run_pair(trial_idx: int, on: bool, log_dir: Path) -> dict:
    """Run a single paired battle. Returns {metrics, status, error}."""
    label = f"eval_trial_{trial_idx:03d}"
    arm = "on" if on else "off"
    artifact_tag = f"PLANNER_ANTI_TR_EVAL_1_{arm}_p{trial_idx:03d}"
    _eval_state["anti_tr"] = on
    try:
        r = await smoke._run_pair(
            WG_TEAM, OPP_TEAM, label, True, True,
            log_dir, trial_idx, arm,
            artifact_tag=artifact_tag
        )
        # Find the audit file
        audit_files = sorted(log_dir.glob(f"*{artifact_tag}*treatment_audit.jsonl"))
        if not audit_files:
            return {"status": "no_audit", "metrics": {}, "won": r.get("won")}
        metrics = compute_metrics(audit_files[0])
        return {
            "status": r.get("status", "ok"),
            "metrics": metrics,
            "won": r.get("won"),
            "audit_path": str(audit_files[0]),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "metrics": {}}


async def run_paired_eval(n_pairs: int, log_dir: Path) -> dict:
    """Run n_pairs paired ON/OFF trials."""
    results = {"on": [], "off": []}
    start = time.time()
    for i in range(n_pairs):
        elapsed = time.time() - start
        print(f"  [{elapsed:.0f}s] Trial {i+1}/{n_pairs}...", flush=True)
        # OFF first (so we have something to compare)
        off = await run_pair(i, on=False, log_dir=log_dir)
        on = await run_pair(i, on=True, log_dir=log_dir)
        results["off"].append(off)
        results["on"].append(on)
        # Heartbeat
        o = off.get("metrics", {})
        n = on.get("metrics", {})
        print(f"    OFF: {off.get('status', '?')} | taunt={o.get('taunt_count', 0)} "
              f"ko={o.get('ko_setter_count', 0)} ignore={o.get('ignore_count', 0)}")
        print(f"    ON:  {on.get('status', '?')} | taunt={n.get('taunt_count', 0)} "
              f"ko={n.get('ko_setter_count', 0)} ignore={n.get('ignore_count', 0)}")
    return results


def aggregate(results: dict) -> dict:
    """Aggregate per-pair metrics to per-arm summary."""
    summary = {}
    for arm in ("on", "off"):
        n = len(results[arm])
        won = sum(1 for r in results[arm] if r.get("won"))
        taunt = sum(r.get("metrics", {}).get("taunt_count", 0) for r in results[arm])
        ko = sum(r.get("metrics", {}).get("ko_setter_count", 0) for r in results[arm])
        fake_out = sum(r.get("metrics", {}).get("fake_out_count", 0) for r in results[arm])
        protect = sum(r.get("metrics", {}).get("protect_count", 0) for r in results[arm])
        pass_switch = sum(r.get("metrics", {}).get("pass_switch_count", 0) for r in results[arm])
        ignore = sum(r.get("metrics", {}).get("ignore_count", 0) for r in results[arm])
        other = sum(r.get("metrics", {}).get("other_count", 0) for r in results[arm])
        tr_set = sum(r.get("metrics", {}).get("tr_set_count", 0) for r in results[arm])
        tr_prevented = sum(1 for r in results[arm] if r.get("metrics", {}).get("tr_prevented", False))
        spam = sum(r.get("metrics", {}).get("spam_violation", 0) for r in results[arm])
        errors = sum(1 for r in results[arm] if r.get("status") != "ok")
        summary[arm] = {
            "n": n,
            "won": won,
            "win_rate": won / n if n else 0,
            "taunt_count": taunt,
            "ko_setter_count": ko,
            "fake_out_count": fake_out,
            "protect_count": protect,
            "pass_switch_count": pass_switch,
            "ignore_count": ignore,
            "other_count": other,
            "tr_set_count": tr_set,
            "tr_prevented_count": tr_prevented,
            "tr_prevented_rate": tr_prevented / n if n else 0,
            "spam_violation": spam,
            "errors": errors,
        }

    # Paired delta
    if results["on"] and results["off"]:
        deltas = []
        for o, n in zip(results["off"], results["on"]):
            ov = 1 if o.get("won") else 0
            nv = 1 if n.get("won") else 0
            deltas.append(nv - ov)
        on_wins = sum(1 for d in deltas if d > 0)
        off_wins = sum(1 for d in deltas if d < 0)
        ties = sum(1 for d in deltas if d == 0)
        summary["paired"] = {
            "n_pairs": len(deltas),
            "on_wins": on_wins,
            "off_wins": off_wins,
            "ties": ties,
            "delta_pp": (summary["on"]["win_rate"] - summary["off"]["win_rate"]) * 100,
        }
    return summary


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", type=int, default=20)
    p.add_argument("--label", default="PLANNER_ANTI_TR_EVAL_1")
    p.add_argument("--out", default="logs/phasePLANNER_ANTI_TR_EVAL_1")
    args = p.parse_args()

    log_dir = ARTIFACT_DIR
    log_dir.mkdir(exist_ok=True)

    print(f"PLANNER-ANTI-TR-EVAL-1 paired eval: {args.pairs} pairs")
    print(f"  WG team: {WG_TEAM}")
    print(f"  Opp team: {OPP_TEAM}")
    print(f"  Custom opp: DoublesTRUserPlayer (TR priority)")
    print()
    results = asyncio.run(run_paired_eval(args.pairs, log_dir))
    summary = aggregate(results)

    # Save raw results
    out_path = Path(f"{args.out}_p{args.pairs}pair.json")
    out_path.write_text(json.dumps({
        "label": args.label,
        "n_pairs": args.pairs,
        "results": results,
        "summary": summary,
    }, indent=2))
    print(f"\nResults saved to {out_path}")

    # Print summary
    print(f"\n=== Summary ({args.pairs} pairs) ===")
    for arm in ("on", "off"):
        s = summary[arm]
        print(f"  {arm.upper():3s}: win_rate={s['win_rate']:.2%} ({s['won']}/{s['n']}) "
              f"taunt={s['taunt_count']} ko={s['ko_setter_count']} "
              f"fo={s['fake_out_count']} prot={s['protect_count']} "
              f"ps={s['pass_switch_count']} other={s['other_count']} "
              f"tr_prevented={s['tr_prevented_count']}/{s['n']} "
              f"spam={s['spam_violation']} errors={s['errors']}")
    if "paired" in summary:
        p = summary["paired"]
        print(f"  PAIRED: ON wins={p['on_wins']} OFF wins={p['off_wins']} "
              f"ties={p['ties']} delta={p['delta_pp']:+.1f}pp")

    return summary


if __name__ == "__main__":
    main()
