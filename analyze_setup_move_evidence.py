#!/usr/bin/env python3
"""Phase SETUP-1 — Setup Move Selection Evidence Audit.

Read-only analysis. Scans audit JSONL artifacts
from COUNTER-5 and CURATED-2 to determine:

- For each setup-move category, how often is a
  setup move LEGAL?
- For each setup-move category, how often is a
  setup move SELECTED?
- For each setup-move category, what is the
  raw score of setup moves (when legal)?
- For each setup-move category, what is the
  score rank of the BEST setup move (1 = top)?
- For each setup-move category, is the best
  setup move ever ranked #1?

If a setup move is consistently:
- legal (move is in v2l1_legal_action_keys)
- but score is low or 0
- and never selected
...then the scoring function lacks setup intent.

If a setup move is:
- legal
- but has high score (rank 1-3)
- but not selected due to joint-order constraints
...then the issue is in joint selection, not scoring.

Categories (per user spec):
  - speed_setup: Tailwind, Trick Room
  - stat_boost: Swords Dance, Nasty Plot, Calm
    Mind, Dragon Dance, Bulk Up, Quiver Dance,
    Shift Gear, Shell Smash, Tail Glow
  - redirection: Follow Me, Rage Powder, Spotlight
  - spread_defense: Wide Guard, Quick Guard,
    Crafty Shield, Mat Block
  - defensive_protect: Protect, Detect,
    King's Shield, Spiky Shield, Baneful Bunker,
    Obstruct, Endure
  - ally_activation: Beat Up, Heal Pulse,
    Life Dew, Pollen Puff (ally)

Output: a per-category summary table and a
verdict on whether scoring lacks intent.

NOT scoring. NOT adding bonus. NOT running
battles. NOT changing source.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---- Setup-move categorization ----
SETUP_CATEGORIES: Dict[str, set] = {
    "speed_setup": {
        "tailwind", "trickroom",
    },
    "stat_boost": {
        "swordsdance", "nastyplot", "calmmind",
        "dragondance", "bulkup", "quiverdance",
        "shiftgear", "shellsmash", "tailglow",
        "coil", "workup", "agility", "rockpolish",
    },
    "redirection": {
        "followme", "ragepowder", "spotlight",
    },
    "spread_defense": {
        "wideguard", "quickguard", "craftyshield",
        "matblock",
    },
    "defensive_protect": {
        "protect", "detect", "kingsshield",
        "spikyshield", "banefulbunker", "obstruct",
        "endure",
    },
    "ally_activation": {
        "beatup", "healpulse", "lifedew",
        "pollenpuff",  # ally side
        "aromatherapy", "healbell",
    },
}

# Build reverse lookup: move_id -> category
MOVE_TO_CATEGORY: Dict[str, str] = {}
for cat, moves in SETUP_CATEGORIES.items():
    for m in moves:
        MOVE_TO_CATEGORY[m] = cat


def norm_move_id(m: str) -> str:
    """Normalize move id: lowercase, strip whitespace."""
    return (m or "").lower().replace(" ", "").replace("-", "").replace("_", "")


def categorize_move(move_id: str) -> Optional[str]:
    """Return category for a move, or None if not a setup move."""
    return MOVE_TO_CATEGORY.get(norm_move_id(move_id))


# ---- Audit JSONL parsing ----
def load_audits(artifacts: List[str]) -> List[Dict[str, Any]]:
    """Load all turns from all audit files."""
    battles = []
    for fp in artifacts:
        path = Path(fp)
        if not path.exists():
            print(f"  WARN: missing {fp}")
            continue
        with open(path) as f:
            for line_no, line in enumerate(f, 1):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                r["_source_file"] = fp
                r["_line_no"] = line_no
                battles.append(r)
    return battles


def analyze_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze one turn's audit data.

    For each slot (0 and 1):
    - Get legal actions
    - Get raw scores
    - Identify which legal moves are setup moves
    - Get the selected action
    - Categorize the selected action

    Returns per-turn dict with:
    - per-slot: legal setup moves, scores, ranks
    - selected: category of selected move per slot
    """
    out: Dict[str, Any] = {
        "turn": turn.get("turn"),
        "slot0": _analyze_slot(turn, 0),
        "slot1": _analyze_slot(turn, 1),
    }
    return out


def _analyze_slot(turn: Dict[str, Any], slot_idx: int) -> Dict[str, Any]:
    """Analyze one slot (0 or 1) of a turn."""
    legal_key = f"v2l1_legal_action_keys_slot{slot_idx}"
    scores_key = f"v2l1_raw_scores_slot{slot_idx}"
    final_key = "v4a_final_action_keys"

    legal_actions = turn.get(legal_key, []) or []
    raw_scores = turn.get(scores_key, {}) or {}
    final_actions = turn.get(final_key, []) or []

    # legal_actions is a list of [kind, move_id, target, ...]
    # raw_scores is a dict {key: score} where key is "kind|move_id|target"
    # We need to match them.

    # Build list of (action, score, category)
    actions_scored = []
    for action in legal_actions:
        if not isinstance(action, list) or len(action) < 2:
            continue
        kind = action[0]
        move_id = action[1]
        target = action[2] if len(action) > 2 else 0
        # Build key for raw_scores
        if kind == "switch":
            key = f"switch|{move_id}|{target}"
        else:
            # For moves, target can be 0, 1, 2, or negative (self)
            key = f"move|{norm_move_id(move_id)}|{target}"
        score = raw_scores.get(key, None)
        cat = categorize_move(move_id) if kind == "move" else None
        actions_scored.append({
            "kind": kind,
            "move_id": move_id,
            "target": target,
            "score": score,
            "category": cat,
        })

    # Rank by score (descending). Higher score = better.
    scored_with_score = [a for a in actions_scored if a["score"] is not None]
    scored_with_score.sort(
        key=lambda a: a["score"] if a["score"] is not None else float("-inf"),
        reverse=True,
    )
    for rank, a in enumerate(scored_with_score, 1):
        a["rank"] = rank

    # Setup move stats
    setup_moves = [a for a in actions_scored if a["category"] is not None]
    setup_legal = len(setup_moves)
    best_setup = None
    if setup_moves:
        setup_with_score = [a for a in setup_moves if a["score"] is not None]
        if setup_with_score:
            best_setup = max(setup_with_score, key=lambda a: a["score"])

    # Determine selected action for this slot
    # final_actions is [[action_for_slot0], [action_for_slot1]]
    selected_action = None
    if final_actions and slot_idx < len(final_actions):
        sel = final_actions[slot_idx]
        if isinstance(sel, list) and len(sel) >= 2:
            selected_action = {
                "kind": sel[0],
                "move_id": sel[1],
                "target": sel[2] if len(sel) > 2 else 0,
            }
            if selected_action["kind"] == "move":
                selected_action["category"] = categorize_move(
                    selected_action["move_id"]
                )
            else:
                selected_action["category"] = None

    return {
        "actions_scored": actions_scored,
        "setup_legal": setup_legal,
        "best_setup": best_setup,
        "selected": selected_action,
    }


def summarize(
    battles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate per-category stats across all turns."""
    # Per-category counters
    cat_legal_turns: Counter = Counter()  # turns where category has any legal move
    cat_selected_turns: Counter = Counter()  # turns where category was selected
    cat_best_score: Dict[str, List[float]] = defaultdict(list)  # best setup score per turn
    cat_best_rank: Dict[str, List[int]] = defaultdict(list)  # rank of best setup move
    cat_score_gap_to_top: Dict[str, List[float]] = defaultdict(list)  # best_setup_score - top_damage_score
    cat_top_score: Dict[str, List[float]] = defaultdict(list)  # top damage move score (for gap)

    # Per-slot counters
    slot_legal_setup: Counter = Counter()  # per slot, how many turns had a legal setup move
    slot_selected_setup: Counter = Counter()  # per slot, how many turns a setup move was selected
    slot_selected_damage: Counter = Counter()
    slot_selected_switch: Counter = Counter()
    slot_selected_protect: Counter = Counter()  # protect is special
    slot_total: Counter = Counter()

    # Per-setup-move stats
    per_move_legal: Counter = Counter()
    per_move_selected: Counter = Counter()
    per_move_mean_score: Dict[str, List[float]] = defaultdict(list)

    # Per-turn count
    n_turns = 0
    n_battles = 0
    seen_battles = set()

    for b in battles:
        battle_id = b.get("battle_tag", "?")
        if battle_id not in seen_battles:
            seen_battles.add(battle_id)
            n_battles += 1

        for t in b.get("audit_turns", []) or []:
            n_turns += 1
            slot_info = analyze_turn(t)

            for slot_idx, slot_key in [(0, "slot0"), (1, "slot1")]:
                sinfo = slot_info[slot_key]
                slot_total[slot_idx] += 1

                # Track legal setup moves by category
                cats_in_slot = set()
                for a in sinfo["actions_scored"]:
                    if a["category"]:
                        cats_in_slot.add(a["category"])
                        per_move_legal[norm_move_id(a["move_id"])] += 1
                        if a["score"] is not None:
                            per_move_mean_score[norm_move_id(a["move_id"])].append(
                                a["score"]
                            )

                for cat in cats_in_slot:
                    cat_legal_turns[cat] += 1
                    slot_legal_setup[slot_idx] += 1

                # Track selected
                sel = sinfo["selected"]
                if sel is None:
                    continue
                if sel["kind"] == "switch":
                    slot_selected_switch[slot_idx] += 1
                    continue
                if sel["kind"] != "move":
                    continue

                if sel["category"] == "defensive_protect":
                    slot_selected_protect[slot_idx] += 1
                    # Note: protect is a setup move, count in setup_intent
                    slot_selected_setup[slot_idx] += 1
                    cat_selected_turns["defensive_protect"] += 1
                    per_move_selected[norm_move_id(sel["move_id"])] += 1
                elif sel["category"]:
                    slot_selected_setup[slot_idx] += 1
                    cat_selected_turns[sel["category"]] += 1
                    per_move_selected[norm_move_id(sel["move_id"])] += 1
                else:
                    slot_selected_damage[slot_idx] += 1

                # Best setup move score for this turn
                # We pick the MAX over both slots
                for cat in cats_in_slot:
                    cat_setup_moves = [
                        a for a in sinfo["actions_scored"]
                        if a["category"] == cat and a["score"] is not None
                    ]
                    if cat_setup_moves:
                        best = max(cat_setup_moves, key=lambda a: a["score"])
                        cat_best_score[cat].append(best["score"])
                        cat_best_rank[cat].append(best.get("rank", 0))

                        # Top damage score for gap
                        damage_moves = [
                            a for a in sinfo["actions_scored"]
                            if a["category"] is None
                            and a["kind"] == "move"
                            and a["score"] is not None
                        ]
                        if damage_moves:
                            top_dmg = max(damage_moves, key=lambda a: a["score"])
                            cat_top_score[cat].append(top_dmg["score"])
                            cat_score_gap_to_top[cat].append(
                                best["score"] - top_dmg["score"]
                            )

    return {
        "n_turns": n_turns,
        "n_battles": n_battles,
        "cat_legal_turns": cat_legal_turns,
        "cat_selected_turns": cat_selected_turns,
        "cat_best_score": cat_best_score,
        "cat_best_rank": cat_best_rank,
        "cat_score_gap_to_top": cat_score_gap_to_top,
        "cat_top_score": cat_top_score,
        "slot_legal_setup": slot_legal_setup,
        "slot_selected_setup": slot_selected_setup,
        "slot_selected_damage": slot_selected_damage,
        "slot_selected_switch": slot_selected_switch,
        "slot_selected_protect": slot_selected_protect,
        "slot_total": slot_total,
        "per_move_legal": per_move_legal,
        "per_move_selected": per_move_selected,
        "per_move_mean_score": per_move_mean_score,
    }


def render_md(stats: Dict[str, Any]) -> str:
    """Render the stats as markdown."""
    lines = []
    lines.append("# SETUP-1 — Setup Move Selection Evidence Audit\n")
    lines.append(f"**Battles analyzed:** {stats['n_battles']}")
    lines.append(f"**Turns analyzed:** {stats['n_turns']}")
    lines.append("")
    lines.append("## Per-Category Summary\n")
    lines.append("| category | legal turns | selected turns | pick rate | mean best score | mean top damage | mean score gap | mean best rank |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cat in SETUP_CATEGORIES:
        legal = stats["cat_legal_turns"].get(cat, 0)
        sel = stats["cat_selected_turns"].get(cat, 0)
        rate = sel / legal if legal > 0 else 0.0
        scores = stats["cat_best_score"].get(cat, [])
        ranks = stats["cat_best_rank"].get(cat, [])
        tops = stats["cat_top_score"].get(cat, [])
        gaps = stats["cat_score_gap_to_top"].get(cat, [])
        mean_score = sum(scores) / len(scores) if scores else 0.0
        mean_top = sum(tops) / len(tops) if tops else 0.0
        mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
        mean_rank = sum(ranks) / len(ranks) if ranks else 0.0
        lines.append(
            f"| {cat} | {legal} | {sel} | {rate*100:.1f}% | "
            f"{mean_score:.1f} | {mean_top:.1f} | "
            f"{mean_gap:+.1f} | {mean_rank:.1f} |"
        )
    lines.append("")

    lines.append("## Per-Slot Selection Distribution\n")
    lines.append("| slot | total | setup picked | damage picked | switch | protect-only |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for s in (0, 1):
        total = stats["slot_total"].get(s, 0)
        setup = stats["slot_selected_setup"].get(s, 0)
        damage = stats["slot_selected_damage"].get(s, 0)
        switch = stats["slot_selected_switch"].get(s, 0)
        protect = stats["slot_selected_protect"].get(s, 0)
        lines.append(
            f"| {s} | {total} | {setup} | {damage} | "
            f"{switch} | {protect} |"
        )
    lines.append("")

    lines.append("## Per-Move Pick Rate (setup moves, top 20 by legal count)\n")
    lines.append("| move | legal | selected | pick rate | mean score |")
    lines.append("|---|---:|---:|---:|---:|")
    move_pairs = []
    for mv in stats["per_move_legal"]:
        legal = stats["per_move_legal"].get(mv, 0)
        sel = stats["per_move_selected"].get(mv, 0)
        scores = stats["per_move_mean_score"].get(mv, [])
        mean_score = sum(scores) / len(scores) if scores else 0.0
        rate = sel / legal if legal > 0 else 0.0
        move_pairs.append((legal, mv, sel, rate, mean_score))
    move_pairs.sort(reverse=True)
    for legal, mv, sel, rate, mean_score in move_pairs[:20]:
        lines.append(
            f"| {mv} | {legal} | {sel} | {rate*100:.1f}% | "
            f"{mean_score:.1f} |"
        )
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_setup_move_evidence.py <audit.jsonl> ...")
        sys.exit(1)

    artifacts = sys.argv[1:]
    print(f"Loading {len(artifacts)} audit files...")
    battles = load_audits(artifacts)
    print(f"Loaded {len(battles)} battles")

    stats = summarize(battles)
    md = render_md(stats)
    print(md)

    # Also write to file
    out_path = Path("/tmp/phaseSETUP1_report.md")
    out_path.write_text(md)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
