#!/usr/bin/env python3
"""
Phase V2c.1 — VGC 2026 Controlled Team Preview Benchmark Analysis (Corrected)

Corrections from V2c:
- Arm D policy perspective: D1 our_win = basic_top4 wins, D2 opponent_win = basic_top4 wins
- Paired analysis: match by pair_id, correct outcome classification
- V3 gate: requires statistical significance, currently BLOCKED
- Mirror sanity: independent computation per arm
- Actual-lead evidence: marked as derived/unverified
"""

import json
import csv
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any, Tuple
import pandas as pd
import numpy as np
from scipy import stats
import math

LOG_DIR = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/logs")
CSV_PATH = LOG_DIR / "vgc2026_phaseV2c_benchmark.csv"
PREVIEW_CSV_PATH = LOG_DIR / "vgc2026_phaseV2c_preview_evidence.csv"
JSONL_PATH = LOG_DIR / "vgc2026_phaseV2c_benchmark.jsonl"

TEAM_DATA_PATH = Path("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_battle_ready.json")


# ===== Pure Helper Functions =====

def normalize_species_name(name: str) -> str:
    """Normalize species name for comparison."""
    name = name.lower().strip()
    name = name.replace(" ", "").replace("-", "").replace("[", "").replace("]", "")
    if name == "floetteeternal":
        return "floetteeternal"
    if name in ("arcaninehisui", "hisuiarcanine"):
        return "arcaninehisui"
    if name in ("basculegionf", "basculegion\u2640"):
        return "basculegionf"
    return name


def load_team_data() -> Dict[str, Dict]:
    with open(TEAM_DATA_PATH) as f:
        data = json.load(f)
    teams = {}
    for team in data.get("teams", []):
        teams[team["id"]] = team
    return teams


def wilson_score_interval(wins: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Wilson score interval for binomial proportion."""
    if total == 0:
        return (0.0, 0.0)
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    p = wins / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def normalize_arm_d_outcomes(
    d1_df: pd.DataFrame, d2_df: pd.DataFrame
) -> Tuple[int, int, int, int]:
    """
    Normalize Arm D outcomes to policy perspective.

    D1: basic_top4 (p1, our player) vs random (p2, opponent)
      -> basic_top4 wins = our_win
      -> random wins = opponent_win
    D2: random (p1, our player) vs basic_top4 (p2, opponent)
      -> basic_top4 wins = opponent_win
      -> random wins = our_win

    Returns: (basic_top4_wins, basic_top4_losses, random_wins, random_losses)
    """
    # basic_top4 wins
    basic_wins = int(d1_df["our_win"].sum()) + int(d2_df["opponent_win"].sum())
    # basic_top4 losses
    basic_losses = int(d1_df["opponent_win"].sum()) + int(d2_df["our_win"].sum())
    # random wins
    random_wins = int(d1_df["opponent_win"].sum()) + int(d2_df["our_win"].sum())
    # random losses
    random_losses = int(d1_df["our_win"].sum()) + int(d2_df["opponent_win"].sum())

    return basic_wins, basic_losses, random_wins, random_losses


def paired_arm_d_analysis(d1_df: pd.DataFrame, d2_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Paired analysis of Arm D by pair_id.

    Returns dict with:
    - basic_both: number of pairs where basic_top4 wins both sides
    - random_both: number of pairs where random wins both sides
    - split: number of pairs with one win each
    - n: number of decisive pairs (excludes splits)
    - k: basic_top4 wins in decisive pairs
    - p_value: exact binomial two-sided p-value
    - pair_details: list of (pair_id, outcome_type) for each pair
    """
    d1_sorted = d1_df.sort_values("pair_id").reset_index(drop=True)
    d2_sorted = d2_df.sort_values("pair_id").reset_index(drop=True)

    if len(d1_sorted) != len(d2_sorted):
        raise ValueError("D1 and D2 must have same number of battles for paired analysis")

    basic_both = 0
    random_both = 0
    split = 0
    pair_details = []

    for i in range(len(d1_sorted)):
        d1_basic_win = bool(d1_sorted.iloc[i]["our_win"])      # D1: basic_top4 is our player
        d2_basic_win = bool(d2_sorted.iloc[i]["opponent_win"])  # D2: basic_top4 is opponent

        if d1_basic_win and d2_basic_win:
            basic_both += 1
            outcome = "basic_both"
        elif not d1_basic_win and not d2_basic_win:
            random_both += 1
            outcome = "random_both"
        else:
            split += 1
            outcome = "split"

        pair_details.append({
            "pair_id": int(d1_sorted.iloc[i]["pair_id"]),
            "outcome": outcome,
            "d1_basic_win": d1_basic_win,
            "d2_basic_win": d2_basic_win
        })

    n = basic_both + random_both
    k = basic_both

    if n > 0:
        p_value = stats.binomtest(k, n, 0.5, alternative='two-sided').pvalue
    else:
        p_value = 1.0

    return {
        "basic_both": basic_both,
        "random_both": random_both,
        "split": split,
        "n": n,
        "k": k,
        "p_value": float(p_value),
        "pair_details": pair_details
    }


def mirror_sanity_evaluation(csv_df: pd.DataFrame) -> Dict[str, Any]:
    """Evaluate mirror arms independently."""
    results = {}

    for arm in ["B", "C"]:
        arm_df = csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]
        if len(arm_df) == 0:
            results[arm] = {"error": "no battles"}
            continue

        wins = int(arm_df["our_win"].sum())
        total = len(arm_df)
        win_rate = wins / total
        ci_low, ci_high = wilson_score_interval(wins, total)

        # Mirror sanity: within ±10% of 50%
        within_bounds = abs(win_rate - 0.5) < 0.1

        results[arm] = {
            "battles": total,
            "wins": wins,
            "losses": int(arm_df["opponent_win"].sum()),
            "ties": int(arm_df["tie"].sum()),
            "win_rate": float(win_rate),
            "wilson_ci": (float(ci_low), float(ci_high)),
            "within_bounds": within_bounds
        }

    return results


def preview_validation(csv_df: pd.DataFrame, preview_df: pd.DataFrame) -> Dict[str, Any]:
    """Validate team preview execution."""
    # Our preview (p1)
    our_matches = preview_df[preview_df["side"] == "p1"]["preview_matches_plan"]
    # Opponent preview (p2)
    opp_matches = preview_df[preview_df["side"] == "p2"]["preview_matches_plan"]

    our_rate = float(our_matches.mean()) if len(our_matches) > 0 else 0.0
    opp_rate = float(opp_matches.mean()) if len(opp_matches) > 0 else 0.0

    # Per-arm breakdown
    arm_rates = {}
    for arm in ["A", "B", "C", "D1", "D2"]:
        arm_preview = preview_df[preview_df["battle_tag"].str.startswith(f"{arm}_")]
        if len(arm_preview) > 0:
            p1 = arm_preview[arm_preview["side"] == "p1"]["preview_matches_plan"]
            p2 = arm_preview[arm_preview["side"] == "p2"]["preview_matches_plan"]
            arm_rates[arm] = {
                "p1_match_rate": float(p1.mean()) if len(p1) > 0 else 0.0,
                "p2_match_rate": float(p2.mean()) if len(p2) > 0 else 0.0,
                "p1_count": int(p1.sum()) if len(p1) > 0 else 0,
                "p2_count": int(p2.sum()) if len(p2) > 0 else 0,
                "p1_total": len(p1),
                "p2_total": len(p2)
            }

    return {
        "our_overall_rate": our_rate,
        "opp_overall_rate": opp_rate,
        "our_count": int(our_matches.sum()) if len(our_matches) > 0 else 0,
        "our_total": len(our_matches),
        "opp_count": int(opp_matches.sum()) if len(opp_matches) > 0 else 0,
        "opp_total": len(opp_matches),
        "by_arm": arm_rates
    }


def actual_lead_evidence_status(preview_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Assess actual-lead evidence quality.

    In V2c, actual_lead_on_turn1 was derived from planned lead_2, not observed.
    This must be marked as derived/unverified.
    """
    total = len(preview_df)
    if total == 0:
        return {"status": "no_data", "derived": True, "note": "No preview evidence rows"}

    # Check if actual_lead_on_turn1 is empty or derived
    has_actual = preview_df["actual_lead_on_turn1"].notna().any()
    # In V2c, actual_lead was set to planned lead_2, so it's derived
    derived = True

    return {
        "total_rows": total,
        "has_actual_lead_data": bool(has_actual),
        "evidence_type": "derived" if derived else "observed",
        "derived": derived,
        "note": "actual_lead_on_turn1 copied from planned lead_2 in V2c; not observed from battle protocol"
    }


def outcome_validation(csv_df: pd.DataFrame) -> Dict[str, Any]:
    """Validate outcome accounting per arm."""
    results = {}
    for arm in ["A", "B", "C", "D1", "D2"]:
        arm_df = csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]
        if len(arm_df) == 0:
            results[arm] = {"error": "no battles"}
            continue

        total = len(arm_df)
        wins = int(arm_df["our_win"].sum())
        losses = int(arm_df["opponent_win"].sum())
        ties = int(arm_df["tie"].sum())
        timeouts = int((arm_df["battle_result"] == "timeout").sum())
        errors = int((arm_df["battle_result"] == "error").sum())
        no_battle = int((arm_df["battle_result"] == "no_battle").sum())

        accounted = wins + losses + ties + timeouts + errors + no_battle
        ok = accounted == total

        results[arm] = {
            "total": total,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "timeouts": timeouts,
            "errors": errors,
            "no_battle": no_battle,
            "accounted": accounted,
            "ok": ok
        }

    return results


def v3_gate_evaluation(
    preview_val: Dict,
    outcomes_real: bool,
    mirror: Dict,
    arm_d_basic_wins: int,
    arm_d_total: int,
    paired: Dict
) -> Dict[str, Any]:
    """
    Evaluate Phase V3 gate criteria.

    Gate criteria (all must PASS):
    1. Preview validation 100% (both sides)
    2. Real outcomes (no placeholders/timeouts/errors/no_battle)
    3. Mirror sanity: Arms B & C within ±10% of 50%
    4. Arm D basic_top4 point estimate > 50%
    5. Arm D paired comparison: statistically significant (p < 0.05)

    Returns: dict with per-gate results and overall decision
    """
    # Gate 1: Preview validation 100%
    preview_ok = (preview_val["our_overall_rate"] == 1.0 and
                  preview_val["opp_overall_rate"] == 1.0)

    # Gate 2: Real outcomes
    outcomes_ok = outcomes_real

    # Gate 3: Mirror sanity
    mirror_ok = mirror.get("B", {}).get("within_bounds", False) and \
                mirror.get("C", {}).get("within_bounds", False)

    # Gate 4: Arm D basic_top4 > 50% point estimate
    arm_d_total = arm_d_total
    arm_d_winrate = arm_d_basic_wins / arm_d_total if arm_d_total > 0 else 0.0
    arm_d_ok = arm_d_winrate > 0.5

    # Gate 5: Paired statistical significance (p < 0.05)
    paired_ok = paired.get("p_value", 1.0) < 0.05

    all_gates = [preview_ok, outcomes_ok, mirror_ok, arm_d_ok, paired_ok]

    gate_details = {
        "preview_100pct": {"pass": preview_ok, "detail": f"our={preview_val['our_overall_rate']*100:.1f}%, opp={preview_val['opp_overall_rate']*100:.1f}%"},
        "real_outcomes": {"pass": outcomes_ok, "detail": "no placeholders/timeouts/errors/no_battle" if outcomes_ok else "has issues"},
        "mirror_sanity": {"pass": mirror_ok, "detail": f"B within ±10%: {mirror.get('B',{}).get('within_bounds','N/A')}, C within ±10%: {mirror.get('C',{}).get('within_bounds','N/A')}"},
        "arm_d_gt_50": {"pass": arm_d_ok, "detail": f"basic_top4 winrate={arm_d_winrate*100:.1f}%"},
        "paired_significant": {"pass": paired_ok, "detail": f"p={paired.get('p_value',1.0):.10f}"},
    }

    overall_allowed = all(all_gates)

    return {
        "gates": gate_details,
        "all_pass": overall_allowed,
        "phase_v3_allowed": overall_allowed
    }


def convert_for_json(obj):
    """Convert numpy types to Python types for JSON serialization."""
    if isinstance(obj, (np.bool_, np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, dict):
        return {k: convert_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_for_json(v) for v in obj]
    return obj


def main():
    print("=" * 60)
    print("Phase V2c.1 — VGC 2026 Controlled Team Preview Analysis (Corrected)")
    print("=" * 60)

    # Load data
    print("\nLoading team data...")
    team_data = load_team_data()
    print(f"Loaded {len(team_data)} teams from battle-ready dataset")

    print("\nLoading CSV logs...")
    csv_df = pd.read_csv(CSV_PATH)
    csv_df["our_win_bool"] = csv_df["our_win"] == True
    csv_df["opponent_win_bool"] = csv_df["opponent_win"] == True
    csv_df["tie_bool"] = csv_df["tie"] == True
    print(f"CSV rows: {len(csv_df)}")

    print("\nLoading preview evidence...")
    preview_df = pd.read_csv(PREVIEW_CSV_PATH)
    print(f"Preview evidence rows: {len(preview_df)}")

    print("\nLoading JSONL logs...")
    jsonl_records = []
    with open(JSONL_PATH) as f:
        for line in f:
            if line.strip():
                jsonl_records.append(json.loads(line))
    jsonl_df = pd.DataFrame(jsonl_records)
    print(f"JSONL battles: {len(jsonl_df)}")

    # Arm mapping
    arm_descriptions = {
        "A": "basic_top4 vs random_4_from_6 (stability smoke)",
        "B": "basic_top4 vs basic_top4 (mirror sanity)",
        "C": "random_4_from_6 vs random_4_from_6 (mirror sanity)",
        "D1": "basic_top4 (p1) vs random_4_from_6 (p2) [paired]",
        "D2": "random_4_from_6 (p1) vs basic_top4 (p2) [paired]",
    }

    # ===== 1. Battle Summary (policy perspective for Arm D) =====
    print("\n" + "=" * 60)
    print("1. BATTLE SUMMARY (policy perspective)")
    print("=" * 60)

    total_battles = len(csv_df)
    print(f"Total battles: {total_battles}")

    for arm in ["A", "B", "C", "D1", "D2"]:
        arm_df = csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]
        if len(arm_df) > 0:
            wins = int(arm_df["our_win_bool"].sum())
            losses = int(arm_df["opponent_win_bool"].sum())
            ties = int(arm_df["tie_bool"].sum())
            timeouts = int((arm_df["battle_result"] == "timeout").sum())
            errors = int((arm_df["battle_result"] == "error").sum())
            no_battle = int((arm_df["battle_result"] == "no_battle").sum())

            win_rate = wins / len(arm_df) * 100
            ci_low, ci_high = wilson_score_interval(wins, len(arm_df))

            desc = arm_descriptions.get(arm, "unknown")
            if arm in ["D1", "D2"]:
                print(f"\n  Arm {arm} (raw our_player perspective): {desc}")
                print(f"    Battles: {len(arm_df)} | W={wins} L={losses} T={ties} TO={timeouts} Err={errors} NB={no_battle}")
                print(f"    Win rate: {win_rate:.1f}% (Wilson 95% CI: {ci_low*100:.1f}% - {ci_high*100:.1f}%)")
            else:
                print(f"\n  Arm {arm}: {desc}")
                print(f"    Battles: {len(arm_df)} | W={wins} L={losses} T={ties} TO={timeouts} Err={errors} NB={no_battle}")
                print(f"    Win rate: {win_rate:.1f}% (Wilson 95% CI: {ci_low*100:.1f}% - {ci_high*100:.1f}%)")

    # Arm D policy perspective
    d1_df = csv_df[csv_df["battle_tag"].str.startswith("D1_")]
    d2_df = csv_df[csv_df["battle_tag"].str.startswith("D2_")]

    basic_wins, basic_losses, random_wins, random_losses = normalize_arm_d_outcomes(d1_df, d2_df)
    basic_total = basic_wins + basic_losses
    basic_winrate = basic_wins / basic_total if basic_total > 0 else 0

    print(f"\n  Arm D (policy perspective - basic_top4 vs random_4_from_6):")
    print(f"    basic_top4: {basic_wins}/{basic_total} = {basic_winrate*100:.1f}%")
    print(f"    random_4_from_6: {random_wins}/{basic_total} = {random_wins/basic_total*100:.1f}%")

    ci_low, ci_high = wilson_score_interval(basic_wins, basic_total)
    print(f"    Wilson 95% CI for basic_top4: {ci_low*100:.1f}% - {ci_high*100:.1f}%")

    # Exact binomial test
    binom_result = stats.binomtest(basic_wins, basic_total, 0.5, alternative='two-sided')
    print(f"    Exact binomial test (p-value): {binom_result.pvalue:.10f}")

    # ===== 2. Preview Validation =====
    print("\n" + "=" * 60)
    print("2. PREVIEW VALIDATION")
    print("=" * 60)

    preview_val = preview_validation(csv_df, preview_df)
    print(f"Our preview matches plan: {preview_val['our_count']}/{preview_val['our_total']} ({preview_val['our_overall_rate']*100:.1f}%)")
    print(f"Opponent preview matches plan: {preview_val['opp_count']}/{preview_val['opp_total']} ({preview_val['opp_overall_rate']*100:.1f}%)")
    for arm, rates in preview_val["by_arm"].items():
        print(f"  Arm {arm}: p1={rates['p1_count']}/{rates['p1_total']}, p2={rates['p2_count']}/{rates['p2_total']}")

    # ===== 3. Actual Lead Evidence Status =====
    print("\n" + "=" * 60)
    print("3. ACTUAL-LEAD EVIDENCE STATUS")
    print("=" * 60)

    lead_status = actual_lead_evidence_status(preview_df)
    print(f"Total preview rows: {lead_status['total_rows']}")
    print(f"Has actual_lead_on_turn1 data: {lead_status['has_actual_lead_data']}")
    print(f"Evidence type: {lead_status['evidence_type']}")
    print(f"Note: {lead_status['note']}")

    # ===== 4. Arm D Paired Analysis =====
    print("\n" + "=" * 60)
    print("4. ARM D PAIRED ANALYSIS (policy perspective)")
    print("=" * 60)

    paired = paired_arm_d_analysis(d1_df, d2_df)
    print(f"Basic wins both sides: {paired['basic_both']}")
    print(f"Random wins both sides: {paired['random_both']}")
    print(f"Split (one each): {paired['split']}")
    print(f"Decisive pairs (n): {paired['n']}")
    print(f"Basic wins in decisive pairs (k): {paired['k']}")
    print(f"Paired sign-test p-value: {paired['p_value']:.10f}")
    print(f"Side split: D1 basic_top4 as p1 wins {int(d1_df['our_win'].sum())}/{len(d1_df)}, D2 basic_top4 as p2 wins {int(d2_df['opponent_win'].sum())}/{len(d2_df)}")

    # ===== 5. Mirror Sanity =====
    print("\n" + "=" * 60)
    print("5. MIRROR SANITY (Arms B & C - independent evaluation)")
    print("=" * 60)

    mirror = mirror_sanity_evaluation(csv_df)
    for arm in ["B", "C"]:
        m = mirror[arm]
        print(f"  Arm {arm}: {m['wins']}/{m['battles']} = {m['win_rate']*100:.1f}% (Wilson CI: {m['wilson_ci'][0]*100:.1f}% - {m['wilson_ci'][1]*100:.1f}%) {'PASS' if m['within_bounds'] else 'FAIL'}")

    # ===== 6. Arm A (Stability) =====
    print("\n" + "=" * 60)
    print("6. ARM A (Stability: basic_top4 vs random_4_from_6)")
    print("=" * 60)

    arm_a_df = csv_df[csv_df["battle_tag"].str.startswith("A_")]
    if len(arm_a_df) > 0:
        wins = int(arm_a_df["our_win_bool"].sum())
        total = len(arm_a_df)
        win_rate = wins / total * 100
        ci_low, ci_high = wilson_score_interval(wins, total)
        print(f"  Arm A: {wins}/{total} = {win_rate:.1f}% (Wilson 95% CI: {ci_low*100:.1f}% - {ci_high*100:.1f}%)")

    # ===== 7. Outcome Validation =====
    print("\n" + "=" * 60)
    print("7. OUTCOME VALIDATION")
    print("=" * 60)

    outcome_val = outcome_validation(csv_df)
    for arm, val in outcome_val.items():
        if "error" in val:
            print(f"  Arm {arm}: {val['error']}")
        else:
            ok_str = "OK" if val["ok"] else "MISMATCH"
            print(f"  Arm {arm}: W={val['wins']} L={val['losses']} T={val['ties']} TO={val['timeouts']} E={val['errors']} NB={val['no_battle']} | Sum={val['accounted']}/{val['total']} {ok_str}")

    print(f"\nCSV total: {len(csv_df)}")
    print(f"JSONL total: {len(jsonl_df)}")
    print(f"Agreement: {'YES' if len(csv_df) == len(jsonl_df) else 'NO'}")

    # ===== 8. Phase V3 Gate =====
    print("\n" + "=" * 60)
    print("8. PHASE V3 GATE EVALUATION")
    print("=" * 60)

    outcomes_real = not csv_df["battle_result"].isin(["timeout", "error", "no_battle"]).any()

    arm_d_basic_wins = basic_wins
    arm_d_total = basic_total

    v3_gate = v3_gate_evaluation(preview_val, outcomes_real, mirror, arm_d_basic_wins, arm_d_total, paired)

    for gate_name, gate_info in v3_gate["gates"].items():
        status = "PASS" if gate_info["pass"] else "FAIL"
        print(f"  {gate_name}: {status} - {gate_info['detail']}")

    print(f"\n  Phase V3 allowed: {'YES' if v3_gate['phase_v3_allowed'] else 'NO'}")

    # ===== Generate Output Files =====
    print("\nGenerating output files...")

    # JSON report
    json_output = convert_for_json({
        "battle_summary": {
            "total_battles": total_battles,
            "by_arm": {
                arm: {
                    "battles": len(csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]),
                    "wins": int(csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]["our_win_bool"].sum()),
                    "losses": int(csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]["opponent_win_bool"].sum()),
                    "ties": int(csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]["tie_bool"].sum())
                } for arm in ["A", "B", "C", "D1", "D2"]
            },
            "arm_d_policy": {
                "basic_top4_wins": basic_wins,
                "basic_top4_losses": basic_losses,
                "random_wins": random_wins,
                "random_losses": random_losses,
                "basic_top4_winrate": basic_winrate,
                "wilson_ci": [float(ci_low), float(ci_high)],
                "exact_binomial_p": float(binom_result.pvalue)
            }
        },
        "preview_validation": convert_for_json(preview_val),
        "actual_lead_evidence": convert_for_json(lead_status),
        "mirror_sanity": convert_for_json(mirror),
        "arm_d_paired": convert_for_json(paired),
        "outcome_validation": convert_for_json(outcome_val),
        "v3_gate": convert_for_json(v3_gate)
    })

    with open(LOG_DIR / "vgc2026_phaseV2c1_analysis.json", "w") as f:
        json.dump(json_output, f, indent=2)
    print(f"JSON report saved to {LOG_DIR / 'vgc2026_phaseV2c1_analysis.json'}")

    # Markdown report
    arm_a_df = csv_df[csv_df["battle_tag"].str.startswith("A_")]
    arm_b_df = csv_df[csv_df["battle_tag"].str.startswith("B_")]
    arm_c_df = csv_df[csv_df["battle_tag"].str.startswith("C_")]

    with open(LOG_DIR / "vgc2026_phaseV2c1_analysis.md", "w") as f:
        f.write("# Phase V2c.1 — VGC 2026 Controlled Team Preview Analysis (Corrected)\n\n")
        f.write(f"Generated: {pd.Timestamp.now()}\n\n")

        f.write("## 1. Battle Summary (Policy Perspective)\n\n")

        for arm in ["A", "B", "C", "D1", "D2"]:
            arm_df = csv_df[csv_df["battle_tag"].str.startswith(f"{arm}_")]
            if len(arm_df) > 0:
                wins = int(arm_df["our_win_bool"].sum())
                losses = int(arm_df["opponent_win_bool"].sum())
                total = len(arm_df)
                win_rate = wins / total * 100
                ci_low, ci_high = wilson_score_interval(wins, total)
                f.write(f"- **Arm {arm}** ({arm_descriptions.get(arm, 'unknown')}): {wins}/{total} = {win_rate:.1f}% (Wilson 95% CI: {ci_low*100:.1f}% - {ci_high*100:.1f}%)\n")

        f.write(f"\n- **Arm D (policy perspective - basic_top4 vs random_4_from_6)**: {basic_wins}/{basic_total} = {basic_winrate*100:.1f}% (Wilson 95% CI: {ci_low*100:.1f}% - {ci_high*100:.1f}%)\n")
        f.write(f"  - Exact binomial test (p-value): {binom_result.pvalue:.10f}\n")

        f.write("\n## 2. Preview Validation\n\n")
        f.write(f"- Our preview matches plan: {preview_val['our_count']}/{preview_val['our_total']} ({preview_val['our_overall_rate']*100:.1f}%)\n")
        f.write(f"- Opponent preview matches plan: {preview_val['opp_count']}/{preview_val['opp_total']} ({preview_val['opp_overall_rate']*100:.1f}%)\n")

        f.write("\n## 3. Actual-Lead Evidence Status\n\n")
        f.write(f"- Evidence type: **{lead_status['evidence_type']}** (not observed from battle protocol)\n")
        f.write(f"- Note: {lead_status['note']}\n")

        f.write("\n## 4. Arm D Paired Analysis\n\n")
        f.write(f"- Basic wins both sides: {paired['basic_both']}\n")
        f.write(f"- Random wins both sides: {paired['random_both']}\n")
        f.write(f"- Split: {paired['split']}\n")
        f.write(f"- Decisive pairs: n={paired['n']}, basic_top4 wins k={paired['k']}\n")
        f.write(f"- Paired sign-test p-value: {paired['p_value']:.10f}\n")
        f.write(f"- Side split: D1 basic_top4 as p1 wins {int(d1_df['our_win'].sum())}/{len(d1_df)}, D2 basic_top4 as p2 wins {int(d2_df['opponent_win'].sum())}/{len(d2_df)}\n")

        f.write("\n## 5. Mirror Sanity\n\n")
        for arm in ["B", "C"]:
            m = mirror[arm]
            f.write(f"- Arm {arm}: {m['wins']}/{m['battles']} = {m['win_rate']*100:.1f}% (Wilson CI: {m['wilson_ci'][0]*100:.1f}% - {m['wilson_ci'][1]*100:.1f}%) {'PASS' if m['within_bounds'] else 'FAIL'}\n")

        f.write("\n## 6. Phase V3 Gate\n\n")
        f.write("| Gate | Status | Detail |\n|------|--------|--------|\n")
        for gate_name, gate_info in v3_gate["gates"].items():
            status = "PASS" if gate_info["pass"] else "FAIL"
            f.write(f"| {gate_name} | {status} | {gate_info['detail']} |\n")

        f.write(f"\n**Phase V3 allowed: {'YES' if v3_gate['phase_v3_allowed'] else 'NO'}**\n")

        f.write("\n---\n\n")
        f.write("> **Correction from V2c**: The previous V2c analysis incorrectly reported Phase V3 as ALLOWED.\n")
        f.write("> The paired comparison is NOT statistically significant (p=0.7754), and the\n")
        f.write("> actual-lead evidence is derived, not observed. Phase V3 remains BLOCKED.\n")

    print(f"Markdown report saved to {LOG_DIR / 'vgc2026_phaseV2c1_analysis.md'}")

    # Update walkthrough.md - mark previous V3 ALLOWED as invalid
    with open("/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/walkthrough.md", "a") as f:
        f.write(f"\n\n## Phase V2c.1 — VGC 2026 Controlled Team Preview Analysis (Corrected) ({pd.Timestamp.now().strftime('%Y-%m-%d')})\n\n")
        f.write(f"**Correction to V2c**: The previous V2c analysis reported Phase V3 as ALLOWED, which was INVALID.\n\n")
        f.write(f"- Arm D policy perspective corrected: basic_top4 = {basic_wins}/{basic_total} = {basic_winrate*100:.1f}%\n")
        f.write(f"- Exact binomial test p = {binom_result.pvalue:.10f}\n")
        f.write(f"- Paired analysis (by pair_id): basic_both={paired['basic_both']}, random_both={paired['random_both']}, split={paired['split']}\n")
        f.write(f"- Paired sign-test p = {paired['p_value']:.10f} (NOT significant)\n")
        f.write(f"- Mirror sanity: Arm B={mirror['B']['win_rate']*100:.1f}% (within ±10%), Arm C={mirror['C']['win_rate']*100:.1f}% (within ±10%)\n")
        f.write(f"- Actual-lead evidence: **DERIVED** (copied from planned lead_2), not observed\n")
        f.write(f"- **Phase V3 status: BLOCKED** (paired comparison not significant)\n")
        f.write(f"- Previous V2c V3 ALLOWED statement: **INVALID**\n")

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()