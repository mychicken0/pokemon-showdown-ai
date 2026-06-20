"""Phase COUNTER-3 — Opponent Setup Counterplay
Cross-Tab Analyzer (read-only).

For each turn where an opponent setup event
fired (any COUNTER-2 opp_actions field), compute:

1. What did the opponent do? (move id, category)
2. What did we select? (per-slot selected action)
3. Was a counterplay candidate legal?
   Counterplay candidates per COUNTER-1:
   - Taunt (disables opp status / setup)
   - Fake Out (priority disruption on turn 1)
   - Encore (locks opp into last move)
   - Spore / sleep / paralysis (status disruption)
   - Protect (negates the move if it's single-target)
   - High-power single-target KO (KO pressure on
     the setup user)
   - Spread bypass (spread move that hits both
     opponents)
4. Did we select a counterplay?

If data is sparse, the script reports
"INSUFFICIENT_DATA" and recommends targeted /
curated probe rather than scoring fix.

Read-only — no scoring change. No benchmark.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional


# Counterplay candidate move IDs (lowercased).
# These are moves that could disrupt an opponent
# setup if selected by us. Grouped by what they
# counter.
COUNTERPLAY_CANDIDATES = {
    # Disables opp status / setup moves (counters
    # Trick Room / Tailwind / setup boost)
    "disables_status": {
        "taunt",
    },
    # Priority disruption on first turn (counters
    # Fake Out / Encore / setup boost)
    "priority_disruption": {
        "fakeout",
    },
    # Locks opp into last move (counters Trick Room
    # / Encore chain)
    "locks_repeat": {
        "encore",
    },
    # Status disruption (sleep / paralysis) — useful
    # against setup users but not always a hard
    # counter
    "status_disruption": {
        "spore", "sleeppowder", "stunspore", "thunderwave",
        "glare", "nuzzle", "yawn",
    },
    # Protect (counters single-target setup / damage)
    "protect": {
        "protect", "detect", "spikyshield", "kingsshield",
        "banefulbunker", "silktrap", "burningbulwark",
        "maxguard", "obstruct",
    },
    # High-power single-target moves that could KO
    # the setup user before the setup completes
    "ko_pressure_high_bp": {
        "moonblast", "moonblastbeam",
        "dracometeor", "earthpower", "heatwave",
        "blizzard", "sludgebomb", "focusblast",
        "psychic", "icebeam", "thunderbolt",
        "energyball", "dazzlinggleam", "shadowball",
        "hydropump", "surf", "scald", "flamethrower",
        "fireblast", "hurricane", "leafstorm", "pollenpuff",
    },
}


# Resolve setup category from opp_actions field name.
def _field_to_category(field_name: str) -> str:
    """Map opp_actions field to its COUNTER-1 category."""
    if field_name in (
        "opponent_used_tailwind",
        "opponent_used_trickroom",
    ):
        return "speed_setup"
    if field_name in (
        "opponent_used_followme",
        "opponent_used_ragepowder",
    ):
        return "redirection_setup"
    if field_name in (
        "opponent_used_fakeout",
        "opponent_used_encore",
        "opponent_used_taunt",
        "opponent_used_quash",
    ):
        return "tempo_disruption"
    if field_name == "opponent_used_stat_boost_setup":
        return "stat_boost_setup"
    if field_name == "opponent_used_screen_setup":
        return "screen_or_field_setup"
    if field_name == "opponent_used_ally_activation_move":
        return "ally_activation"
    if field_name == "opponent_used_absorb_redirect_ally":
        return "partner_absorb_redirect"
    if field_name in (
        "opponent_used_spread",
        "opponent_used_wide_guard",
        "opponent_used_quick_guard",
    ):
        return "spread_defense"
    if field_name == "opponent_used_protect":
        return "protect_opp"
    return "other"


# Counterplay category for each opp setup category.
# (informational — what kind of counterplay is most
# relevant for each setup).
COUNTERPLAY_RELEVANCE = {
    "speed_setup": ["disables_status", "priority_disruption"],
    "redirection_setup": ["disables_status", "ko_pressure_high_bp"],
    "tempo_disruption": ["protect", "ko_pressure_high_bp"],
    "stat_boost_setup": ["disables_status", "priority_disruption", "ko_pressure_high_bp"],
    "screen_or_field_setup": ["disables_status", "ko_pressure_high_bp"],
    "ally_activation": ["disables_status", "priority_disruption"],
    "partner_absorb_redirect": ["ko_pressure_high_bp", "locks_repeat"],
    "spread_defense": ["ko_pressure_high_bp"],
    "protect_opp": ["ko_pressure_high_bp"],
    "other": [],
}


def _normalize_move_id(mid: str) -> str:
    """Normalize a move id to lowercase alnum."""
    return "".join(c for c in (mid or "").lower() if c.isalnum())


def _extract_legal_move_ids(legal_keys: List[Any]) -> set:
    """Pull move IDs out of v4a_legal_action_keys."""
    ids = set()
    for k in legal_keys or []:
        if (
            isinstance(k, list)
            and len(k) >= 2
            and k[0] == "move"
            and isinstance(k[1], str)
        ):
            ids.add(_normalize_move_id(k[1]))
    return ids


def _extract_selected_move_id(selected_action_move_id: Optional[str]) -> str:
    return _normalize_move_id(selected_action_move_id or "")


def _run_crosstab(artifacts: List[str]) -> Dict[str, Any]:
    """Cross-tab opp setup events against our
    selections and legal counterplay availability."""
    results = {
        "n_artifacts": 0,
        "n_battles": 0,
        "n_turns_total": 0,
        # Per-category counterplay audit
        "per_category": defaultdict(
            lambda: {
                "opp_setup_turns": 0,
                "we_selected_counterplay": 0,
                "counterplay_legal_but_not_selected": 0,
                "counterplay_legal_and_selected": 0,
                "no_counterplay_legal": 0,
                "sample_turns": [],
            }
        ),
        # Per-counterplay-move type stats
        "per_counterplay_type": defaultdict(
            lambda: {
                "legal_turns": 0,
                "selected_turns": 0,
            }
        ),
        # Per-pair breakdown
        "per_pair": defaultdict(
            lambda: {
                "n_turns": 0,
                "n_opp_setup_turns": 0,
                "n_counterplay_legal": 0,
                "n_counterplay_selected": 0,
            }
        ),
        # All raw counterplay-gap samples (for
        # dry-run later — empty since raw scores
        # are not persisted; just an artifact for
        # COUNTER-4).
        "all_legal_not_selected_samples": [],
        # Per-counterplay-type legal-not-selected counts
        "counterplay_legal_not_selected_by_type": defaultdict(int),
    }

    opp_setup_field_names = (
        "opponent_used_tailwind",
        "opponent_used_trickroom",
        "opponent_used_followme",
        "opponent_used_ragepowder",
        "opponent_used_fakeout",
        "opponent_used_encore",
        "opponent_used_taunt",
        "opponent_used_quash",
        "opponent_used_stat_boost_setup",
        "opponent_used_screen_setup",
        "opponent_used_ally_activation_move",
        "opponent_used_absorb_redirect_ally",
        "opponent_used_spread",
        "opponent_used_wide_guard",
        "opponent_used_quick_guard",
        "opponent_used_protect",
    )

    for fp in artifacts:
        if not os.path.exists(fp):
            continue
        results["n_artifacts"] += 1
        with open(fp) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                results["n_battles"] += 1
                # Infer pair_id from filename
                pair_id = fp.split("_")[-1].split(".")[0]
                for t in r.get("audit_turns", []) or []:
                    results["n_turns_total"] += 1
                    results["per_pair"][pair_id]["n_turns"] += 1
                    opp_a = t.get("opp_actions", {}) or {}
                    # Identify which setup fields fired
                    fired_fields = [
                        f for f in opp_setup_field_names
                        if opp_a.get(f)
                    ]
                    if not fired_fields:
                        continue
                    results["per_pair"][pair_id]["n_opp_setup_turns"] += 1

                    # Categorize the dominant setup event
                    # (highest-priority category wins; tie
                    # broken by field order).
                    primary_field = fired_fields[0]
                    category = _field_to_category(primary_field)

                    s0 = t.get("slot_0", {}) or {}
                    s1 = t.get("slot_1", {}) or {}
                    sel0 = _extract_selected_move_id(
                        s0.get("selected_action_move_id")
                    )
                    sel1 = _extract_selected_move_id(
                        s1.get("selected_action_move_id")
                    )
                    legal0 = _extract_legal_move_ids(
                        t.get("v4a_legal_action_keys_slot0", [])
                    )
                    legal1 = _extract_legal_move_ids(
                        t.get("v4a_legal_action_keys_slot1", [])
                    )

                    # Aggregate per-counterplay-type stats
                    # across both slots.
                    selected_set = {sel0, sel1}
                    legal_union = legal0 | legal1
                    for ctype, moves in COUNTERPLAY_CANDIDATES.items():
                        moves_in_legal = moves & legal_union
                        if moves_in_legal:
                            results["per_counterplay_type"][ctype][
                                "legal_turns"
                            ] += 1
                            if moves_in_legal & selected_set:
                                results["per_counterplay_type"][ctype][
                                    "selected_turns"
                                ] += 1

                    # What counterplay categories are
                    # relevant for this opp setup?
                    relevant = COUNTERPLAY_RELEVANCE.get(
                        category, []
                    )
                    if not relevant:
                        results["per_category"][category][
                            "opp_setup_turns"
                        ] += 1
                        results["per_category"][category][
                            "no_counterplay_legal"
                        ] += 1
                        continue
                    # Did we have a relevant counterplay
                    # move in legal?
                    relevant_moves = set()
                    for ctype in relevant:
                        relevant_moves |= COUNTERPLAY_CANDIDATES.get(
                            ctype, set()
                        )
                    counterplay_legal = (
                        relevant_moves & legal_union
                    )
                    counterplay_selected = (
                        relevant_moves & selected_set
                    )
                    results["per_category"][category][
                        "opp_setup_turns"
                    ] += 1
                    if counterplay_legal:
                        results["per_pair"][pair_id][
                            "n_counterplay_legal"
                        ] += 1
                        if counterplay_selected:
                            results["per_pair"][pair_id][
                                "n_counterplay_selected"
                            ] += 1
                            results["per_category"][category][
                                "counterplay_legal_and_selected"
                            ] += 1
                            results["per_category"][category][
                                "we_selected_counterplay"
                            ] += 1
                        else:
                            results["per_category"][category][
                                "counterplay_legal_but_not_selected"
                            ] += 1
                            # Track which specific counterplay
                            # moves were LEGAL but not selected.
                            # (Track only the LEGAL-but-not-selected
                            # subset, not all category moves.)
                            legal_counterplay_not_selected = (
                                relevant_moves & legal_union
                            ) - selected_set
                            for mv in legal_counterplay_not_selected:
                                # Bucket by counterplay type.
                                for ctype, moves in (
                                    COUNTERPLAY_CANDIDATES.items()
                                ):
                                    if mv in moves:
                                        results[
                                            "counterplay_legal_not_selected_by_type"
                                        ][ctype] += 1
                                        break
                            results[
                                "all_legal_not_selected_samples"
                            ].append(
                                {
                                    "pair_id": pair_id,
                                    "turn": t.get("turn"),
                                    "category": category,
                                    "opp_setup_fields": fired_fields,
                                    "selected": [sel0, sel1],
                                    "counterplay_legal": sorted(
                                        relevant_moves & legal_union
                                    ),
                                    "missing_legal": sorted(
                                        legal_counterplay_not_selected
                                    ),
                                }
                            )
                            if len(
                                results[
                                    "per_category"
                                ][category]["sample_turns"]
                            ) < 5:
                                results["per_category"][category][
                                    "sample_turns"
                                ].append(
                                    {
                                        "turn": t.get("turn"),
                                        "opp_setup_fields": fired_fields,
                                        "selected": [sel0, sel1],
                                        "counterplay_legal": sorted(
                                            relevant_moves & legal_union
                                        ),
                                        "missing_legal": sorted(
                                            legal_counterplay_not_selected
                                        ),
                                    }
                                )
                    else:
                        results["per_category"][category][
                            "no_counterplay_legal"
                        ] += 1
    return results


def _format_results(results: Dict[str, Any]) -> str:
    out = []
    out.append("=== COUNTER-3 Cross-Tab Summary ===")
    out.append(f"Artifacts analyzed: {results['n_artifacts']}")
    out.append(
        f"Battles: {results['n_battles']}, "
        f"turns: {results['n_turns_total']}"
    )
    out.append("")

    # Per-pair
    out.append("=== Per-pair breakdown ===")
    out.append(
        f"{'pair':>10} {'turns':>6} "
        f"{'opp_setup':>10} {'cp_legal':>10} {'cp_selected':>12}"
    )
    for pair_id, d in sorted(results["per_pair"].items()):
        out.append(
            f"{pair_id:>10} {d['n_turns']:>6} "
            f"{d['n_opp_setup_turns']:>10} {d['n_counterplay_legal']:>10} "
            f"{d['n_counterplay_selected']:>12}"
        )
    out.append("")

    # Per-category
    out.append("=== Per-category cross-tab ===")
    out.append(
        f"{'category':>22} "
        f"{'turns':>6} {'cp_legal':>10} {'cp_picked':>10} "
        f"{'missed':>8} {'no_cp':>8}"
    )
    for cat in sorted(results["per_category"].keys()):
        d = results["per_category"][cat]
        missed = d["counterplay_legal_but_not_selected"]
        no_cp = d["no_counterplay_legal"]
        out.append(
            f"{cat:>22} {d['opp_setup_turns']:>6} "
            f"{d['counterplay_legal_and_selected'] + missed:>10} "
            f"{d['counterplay_legal_and_selected']:>10} "
            f"{missed:>8} {no_cp:>8}"
        )
    out.append("")

    # Per-counterplay-type
    out.append("=== Per-counterplay-type availability ===")
    out.append(
        f"{'counterplay_type':>26} {'legal_turns':>13} "
        f"{'selected_turns':>15} {'pick_rate':>10}"
    )
    for ctype, d in sorted(
        results["per_counterplay_type"].items(),
        key=lambda x: -x[1]["legal_turns"],
    ):
        if d["legal_turns"] == 0:
            continue
        rate = (
            100 * d["selected_turns"] / d["legal_turns"]
            if d["legal_turns"] > 0
            else 0
        )
        out.append(
            f"{ctype:>26} {d['legal_turns']:>13} "
            f"{d['selected_turns']:>15} {rate:>9.1f}%"
        )
    out.append("")

    # Per-counterplay-type missed
    out.append("=== Counterplay legal-but-not-selected by type ===")
    for ctype, c in sorted(
        results[
            "counterplay_legal_not_selected_by_type"
        ].items(),
        key=lambda x: -x[1],
    ):
        out.append(f"  {ctype}: {c} turns")
    out.append("")

    # Sample turns for the largest category
    out.append("=== Sample turns (opp setup + counterplay status) ===")
    samples = results["all_legal_not_selected_samples"][:10]
    if not samples:
        out.append("(no counterplay-missed samples to show)")
    else:
        for s in samples:
            out.append(
                f"  pair={s['pair_id']} turn={s['turn']} "
                f"category={s['category']} "
                f"opp_setup={s['opp_setup_fields']}"
            )
            out.append(
                f"    selected={s['selected']} "
                f"counterplay_legal={s['counterplay_legal']}"
            )
            out.append(
                f"    missing_legal={s['missing_legal']}"
            )
    return "\n".join(out)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact", action="append", default=None,
        help="Audit JSONL artifact path (can repeat). "
        "If omitted, all logs/phaseCOUNTER5_*.jsonl "
        "artifacts are auto-discovered.",
    )
    parser.add_argument(
        "--md", default=None,
        help="Optional Markdown output path.",
    )
    args = parser.parse_args()

    if not args.artifact:
        # Auto-discover: glob vgc2026_phaseCOUNTER5_*.jsonl
        import glob
        args.artifact = sorted(glob.glob("logs/vgc2026_phaseCOUNTER5_*.jsonl"))
        if not args.artifact:
            print("No artifacts found via "
                  "logs/vgc2026_phaseCOUNTER5_*.jsonl")
            return

    results = _run_crosstab(args.artifact)
    text = _format_results(results)

    # Coverage / data-sufficiency verdict
    n_opp_setup = sum(
        d["opp_setup_turns"]
        for d in results["per_category"].values()
    )
    n_cp_legal = sum(
        d["counterplay_legal_and_selected"]
        + d["counterplay_legal_but_not_selected"]
        for d in results["per_category"].values()
    )

    verdict_lines = []
    verdict_lines.append("")
    verdict_lines.append("=== Data-sufficiency verdict ===")
    if n_opp_setup < 10:
        verdict_lines.append(
            f"INSUFFICIENT_DATA: only {n_opp_setup} opp setup turns "
            f"observed across {results['n_battles']} battles. "
            "Recommendation: run targeted/curated probe with "
            "teams that include opp Trick Room / Tailwind / setup "
            "users (e.g. Indeedee-F / Porygon2 / Alcremie / Whimsicott "
            "leads). Do NOT close the track as 'healthy' — "
            "evidence is too thin to support any conclusion."
        )
    elif n_cp_legal < 3:
        verdict_lines.append(
            f"INSUFFICIENT_DATA: only {n_cp_legal} counterplay-legal "
            f"turns. Sample is too small to score a counterplay "
            "scoring helper."
        )
    else:
        verdict_lines.append(
            f"SUFFICIENT_DATA: {n_opp_setup} opp setup turns, "
            f"{n_cp_legal} counterplay-legal turns. Cross-tab "
            "is informative enough to assess counterplay "
            "scoring."
        )
    verdict = "\n".join(verdict_lines)

    print(text)
    print(verdict)

    if args.md:
        with open(args.md, "w") as f:
            f.write("# Phase COUNTER-3 — Cross-Tab Analysis\n\n")
            f.write(text)
            f.write("\n")
            f.write(verdict)
            f.write("\n")


if __name__ == "__main__":
    main()
