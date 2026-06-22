#!/usr/bin/env python3
"""Phase SETUP-4 — Bonus Magnitude Dry-Run.

Read-only. Sweeps setup_intent_speed_setup_bonus
across {350, 450, 550, 650, 750} and counts
how many turns would flip Tailwind / Trick Room
from "not top" to "top" in slot scoring.

For each flip, also flags "over-flip": the
case where the displaced damage move was a
likely KO (heuristic: damage score > 500
with opp HP < 0.5, OR damage score > 700).

No scoring change. No battle run. No default
flip.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SETUP_MOVES = {"tailwind", "trickroom"}

BONUS_MAGNITUDES = [350, 450, 550, 650, 750]

# Game-phase windows
EARLY_MAX_TURN = 3
MID_MAX_TURN = 7

# Over-flip heuristic
LIKELY_KO_SCORE = 500.0
VERY_LIKELY_KO_SCORE = 700.0
LIKELY_KO_HP_THRESHOLD = 0.5


def norm_move(m):
    return (m or "").lower().replace(" ", "").replace("-", "")


def game_phase(turn: int) -> str:
    if turn <= EARLY_MAX_TURN:
        return "early"
    if turn <= MID_MAX_TURN:
        return "mid"
    return "late"


def is_likely_ko(
    damage_score: Optional[float],
    opp_hp: Optional[float],
) -> bool:
    """Heuristic: would the displaced damage
    move be a likely KO?

    Heuristic:
    - very high score (> 700) is likely a KO
      regardless of HP.
    - moderate score (> 500) with low opp HP
      (< 50%) is a likely KO.
    """
    if damage_score is None:
        return False
    if damage_score >= VERY_LIKELY_KO_SCORE:
        return True
    if (
        damage_score >= LIKELY_KO_SCORE
        and opp_hp is not None
        and opp_hp < LIKELY_KO_HP_THRESHOLD
    ):
        return True
    return False


def load_baseline_audits(artifacts: List[str]) -> List[Dict[str, Any]]:
    """Load all turns from baseline audit files
    (no SETUP-3A bonus applied). We use baseline
    so TW/TR scores are the natural scores."""
    out = []
    for fp in artifacts:
        with open(fp) as f:
            for line_no, line in enumerate(f, 1):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                r["_source_file"] = fp
                r["_line_no"] = line_no
                if "_baseline" in fp:
                    out.append(r)
                else:
                    # For non-baseline files, skip —
                    # we want clean (no-bonus) data.
                    # But COUNTER-5/CURATED-2 don't
                    # have SETUP-3A flag, so they're
                    # also clean. Include them.
                    out.append(r)
    return out


def per_slot_stats(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    """For each slot (0, 1), compute:
    - setup_natural: max score among setup moves
      (TW/TR) in legal actions
    - top_damage: max score among non-setup moves
    - top_damage_move: id of top damage move
    - opp_hp: best guess at the opp's HP
    - selected_category: 'setup' or 'damage' or
      'switch' based on the selected action
    """
    out = []
    for slot_idx in (0, 1):
        legal_key = f"v2l1_legal_action_keys_slot{slot_idx}"
        scores_key = f"v2l1_raw_scores_slot{slot_idx}"
        legal = turn.get(legal_key, []) or []
        scores = turn.get(scores_key, {}) or {}
        # Selected action for this slot
        final_actions = turn.get("v4a_final_action_keys", []) or []
        sel = (
            final_actions[slot_idx]
            if slot_idx < len(final_actions)
            else None
        )

        # Build per-action score list
        actions_scored = []
        for action in legal:
            if not isinstance(action, list) or len(action) < 2:
                continue
            kind = action[0]
            move_id = action[1]
            target = action[2] if len(action) > 2 else 0
            if kind == "switch":
                key = f"switch|{move_id}|{target}"
            else:
                key = f"move|{norm_move(move_id)}|{target}"
            score = scores.get(key, None)
            actions_scored.append({
                "kind": kind,
                "move_id": move_id,
                "target": target,
                "score": score,
                "is_setup": norm_move(move_id) in SETUP_MOVES,
            })

        # Setup move max score (natural)
        setup_actions = [
            a for a in actions_scored
            if a["is_setup"] and a["score"] is not None
        ]
        setup_natural = (
            max(a["score"] for a in setup_actions)
            if setup_actions
            else None
        )
        # Top damage move
        damage_actions = [
            a for a in actions_scored
            if not a["is_setup"]
            and a["kind"] == "move"
            and a["score"] is not None
        ]
        if damage_actions:
            top_dmg = max(
                damage_actions, key=lambda a: a["score"]
            )
            top_damage = top_dmg["score"]
            top_damage_move = top_dmg["move_id"]
        else:
            top_damage = None
            top_damage_move = None

        # Selected category
        if sel is None or not isinstance(sel, list):
            sel_cat = "unknown"
        elif sel[0] == "switch":
            sel_cat = "switch"
        elif sel[0] == "move":
            mid = norm_move(sel[1]) if len(sel) > 1 else ""
            if mid in SETUP_MOVES:
                sel_cat = "setup"
            else:
                sel_cat = "damage"
        else:
            sel_cat = "unknown"

        # Opp HP from state snapshot
        opp_hp = None
        ss = turn.get("state_snapshot", {}) or {}
        # state_snapshot has opp_active_hp_fraction
        # as a list (one entry per opp active mon).
        # Use the LOWEST value (most damageable).
        opp_hp_fracs = ss.get("opp_active_hp_fraction", []) or []
        for hp in opp_hp_fracs:
            if hp is None:
                continue
            if opp_hp is None or hp < opp_hp:
                opp_hp = hp
        # Fallback: check old schema
        if opp_hp is None:
            opp_active = ss.get("opp_active", []) or []
            for mon in opp_active:
                if not isinstance(mon, dict):
                    continue
                hp = mon.get("hp")
                if hp is None:
                    hp = mon.get("hp_fraction")
                if hp is None:
                    continue
                if opp_hp is None or hp < opp_hp:
                    opp_hp = hp

        out.append({
            "slot": slot_idx,
            "setup_natural": setup_natural,
            "top_damage": top_damage,
            "top_damage_move": top_damage_move,
            "opp_hp": opp_hp,
            "selected_category": sel_cat,
        })
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_setup4_bonus_sweep.py <audit.jsonl> ...")
        sys.exit(1)

    artifacts = sys.argv[1:]
    print(f"Loading {len(artifacts)} audit files...")
    battles = load_baseline_audits(artifacts)
    print(f"Loaded {len(battles)} battle records")

    # Aggregate per-turn slot stats
    rows = []
    for b in battles:
        bt = b.get("battle_tag", "?")
        for t in b.get("audit_turns", []) or []:
            turn_n = t.get("turn", "?")
            phase = (
                game_phase(int(turn_n))
                if isinstance(turn_n, int)
                else "unknown"
            )
            slots = per_slot_stats(t)
            for s in slots:
                rows.append({
                    "battle_tag": bt,
                    "turn": turn_n,
                    "phase": phase,
                    "slot": s["slot"],
                    "setup_natural": s["setup_natural"],
                    "top_damage": s["top_damage"],
                    "top_damage_move": s["top_damage_move"],
                    "opp_hp": s["opp_hp"],
                    "selected_category": s["selected_category"],
                })

    print(f"Total slot-turns analyzed: {len(rows)}")

    # Per-magnitude flip count
    n_with_setup_natural = sum(
        1 for r in rows if r["setup_natural"] is not None
    )
    print(f"Slot-turns with setup move legal: {n_with_setup_natural}")
    n_top_damage = sum(
        1 for r in rows if r["top_damage"] is not None
    )
    print(f"Slot-turns with damage move legal: {n_top_damage}")

    # For each magnitude, count flips
    print()
    print("=== Per-magnitude flip count ===")
    print(
        f"{'bonus':>6} | {'flips':>6} | {'over_flips':>10} | "
        f"{'over_rate':>10} | {'early':>6} | {'mid':>6} | "
        f"{'late':>6} | {'sel_setup_now':>13}"
    )
    print("-" * 80)
    overall = {}
    for bonus in BONUS_MAGNITUDES:
        flips = 0
        over_flips = 0
        per_phase = Counter()
        sel_setup_now = 0
        for r in rows:
            if r["setup_natural"] is None:
                continue
            if r["top_damage"] is None:
                # No damage alternative, setup would be selected.
                # Don't count as a "flip" (was already top).
                continue
            boosted = r["setup_natural"] + bonus
            if boosted > r["top_damage"]:
                # Setup would win with this bonus.
                flips += 1
                per_phase[r["phase"]] += 1
                if is_likely_ko(
                    r["top_damage"], r["opp_hp"]
                ):
                    over_flips += 1
                if r["selected_category"] == "setup":
                    sel_setup_now += 1
        over_rate = (
            over_flips / flips * 100 if flips else 0.0
        )
        print(
            f"{bonus:>6} | {flips:>6} | {over_flips:>10} | "
            f"{over_rate:>9.1f}% | {per_phase['early']:>6} | "
            f"{per_phase['mid']:>6} | {per_phase['late']:>6} | "
            f"{sel_setup_now:>13}"
        )
        overall[bonus] = {
            "flips": flips,
            "over_flips": over_flips,
            "over_rate": over_rate,
            "per_phase": dict(per_phase),
            "sel_setup_now": sel_setup_now,
        }

    # Detail: per-turn flips at the recommended magnitude
    # User said "+550/+650 flip speed-setup turns and no
    # over-flip → SETUP-5". So check 550 first.
    print()
    print("=== Flip detail at +550 ===")
    flips_550 = []
    for r in rows:
        if r["setup_natural"] is None or r["top_damage"] is None:
            continue
        if r["setup_natural"] + 550 > r["top_damage"]:
            flips_550.append(r)
    print(f"Total flips at +550: {len(flips_550)}")
    for r in flips_550[:10]:
        print(
            f"  {r['battle_tag']} T{r['turn']} slot{r['slot']} "
            f"phase={r['phase']}: setup_natural={r['setup_natural']:.1f} "
            f"top_dmg={r['top_damage']:.1f} ({r['top_damage_move']}) "
            f"opp_hp={r['opp_hp']} selected={r['selected_category']}"
        )

    # Verdict
    print()
    print("=== Verdict ===")
    if overall[550]["over_rate"] > 20:
        print("MAGNITUDE_RISK: +550 over-flip rate > 20%")
    elif overall[550]["flips"] > 0:
        print(
            f"OK_AT_550: {overall[550]['flips']} flips, "
            f"{overall[550]['over_rate']:.1f}% over-flip"
        )
    else:
        print("BONUS_INERT_AT_550: 0 flips")

    if overall[650]["over_rate"] > 20:
        print("MAGNITUDE_RISK: +650 over-flip rate > 20%")
    elif overall[650]["flips"] > overall[550]["flips"]:
        print(
            f"+650 more flips than +550: "
            f"{overall[650]['flips']} vs {overall[550]['flips']}"
        )

    # Output JSON for report
    out_path = Path("/tmp/phaseSETUP4_dryrun.json")
    with open(out_path, "w") as f:
        json.dump(
            {
                "n_slot_turns": len(rows),
                "n_with_setup_natural": n_with_setup_natural,
                "n_with_top_damage": n_top_damage,
                "per_magnitude": overall,
                "flips_at_550_sample": flips_550[:20],
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
