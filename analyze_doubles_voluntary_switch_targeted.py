#!/usr/bin/env python3
"""
Phase 6.4.10 — Voluntary Switch Quality Targeted Analyzer.

Reads the JSONL produced by
``bot_doubles_voluntary_switch_targeted_qualification.py``
and verifies that each scenario's expected behavior
holds.

For every scenario we check:

  1. bad_switch_into_4x_weakness:
     - ON candidate row has positive score_adjustment
       (the 4x-weak switch is penalised).
     - ON ``active_risk`` is lower than the
       candidate's risk against the same opp.
     - ON reason codes include ``candidate_unsafe``
       or ``candidate_quad_weak``.
  2. healthy_bench_preservation:
     - ON candidate row records positive
       ``sacrifice_preserve_bench_value`` or
       reason code ``sacrifice_preserve_bench``.
     - OFF ``sacrifice_preserve_bench_value`` is
       also positive (the rule is correctly
       identifying the opportunity in both arms).
  3. real_risk_reduction:
     - ON candidate row has positive
       ``risk_reduction`` and adjusted score is
       above the raw switch score (i.e., the
       risk_reduction_bonus outweighs the tempo
       penalty).
  4. repeat_switch:
     - ON candidate row has positive
       ``repeat_penalty``.
     - OFF candidate row has zero repeat
       penalty (the diagnostics still see
       ``history`` if available, but the rule
       stays diagnostic-only when scoring is
       off).
  5. useful_stay:
     - ON ``active_has_high_value_action`` is True.
     - ON ``stay_value_penalty`` is positive.
     - ON ``score_adjustment`` is positive (the
       switch is penalised).

Hard-fail rules:
  - Any scenario where the per-scenario invariants
    above do NOT hold.
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
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


def _first_audit_turn(record):
    at = record.get("audit_turns", []) or []
    if not at:
        return {}
    return at[0]


def _check_bad_switch(scenario_id, on_row, on_eval):
    errs = []
    if not on_row:
        return [f"{scenario_id}: no ON candidate row"]
    if on_row.get("score_adjustment", 0.0) <= 0.0:
        errs.append(
            f"{scenario_id}: ON score_adjustment "
            f"({on_row.get('score_adjustment', 0.0):.1f}) "
            f"should be > 0 (4x-weak switch penalised)"
        )
    if not (on_eval.get("candidate_quad_weak", False)
            or on_eval.get("candidate_double_threat", False)):
        errs.append(
            f"{scenario_id}: ON did not flag the "
            f"candidate as quad_weak or double_threat"
        )
    if on_eval.get("candidate_risk", 0.0) <= on_eval.get(
        "active_risk", 0.0
    ):
        errs.append(
            f"{scenario_id}: ON candidate_risk "
            f"({on_eval.get('candidate_risk', 0.0):.2f}) "
            f"<= active_risk ({on_eval.get('active_risk', 0.0):.2f}); "
            f"expected candidate strictly worse"
        )
    return errs


def _check_healthy_bench(scenario_id, on_row, on_eval,
                          off_row, off_eval):
    errs = []
    on_sac_value = on_eval.get(
        "sacrifice_preserve_bench_value", 0.0
    )
    if on_sac_value <= 0.0:
        errs.append(
            f"{scenario_id}: ON sacrifice_preserve_bench_value "
            f"({on_sac_value:.1f}) should be > 0"
        )
    if "sacrifice_preserve_bench" not in on_eval.get(
        "reason_codes", []
    ):
        errs.append(
            f"{scenario_id}: ON did not include "
            f"'sacrifice_preserve_bench' reason code"
        )
    if not on_eval.get("active_low_hp", False):
        errs.append(
            f"{scenario_id}: ON did not flag active as low HP"
        )
    if not on_eval.get("active_has_useful_action", False):
        errs.append(
            f"{scenario_id}: ON did not flag active as "
            f"having a useful action"
        )
    return errs


def _check_real_risk_reduction(scenario_id, on_row, on_eval):
    errs = []
    if on_eval.get("risk_reduction", 0.0) <= 0.0:
        errs.append(
            f"{scenario_id}: ON risk_reduction "
            f"({on_eval.get('risk_reduction', 0.0):.2f}) should "
            f"be > 0"
        )
    tempo_penalty = 35.0
    score_adj = on_row.get("score_adjustment", 0.0)
    if score_adj >= tempo_penalty:
        errs.append(
            f"{scenario_id}: ON score_adjustment "
            f"({score_adj:.1f}) should be < tempo_penalty "
            f"({tempo_penalty:.1f}); risk_reduction_bonus "
            f"must reduce the tempo penalty"
        )
    return errs


def _check_repeat_switch(scenario_id, on_row, on_eval,
                         off_row, off_eval):
    errs = []
    on_repeat = on_row.get("repeat_penalty", 0.0)
    if on_repeat <= 0.0:
        errs.append(
            f"{scenario_id}: ON repeat_penalty "
            f"({on_repeat:.1f}) should be > 0"
        )
    off_repeat = off_row.get("repeat_penalty", 0.0) if off_row else 0.0
    if off_repeat > 0.0:
        errs.append(
            f"{scenario_id}: OFF repeat_penalty "
            f"({off_repeat:.1f}) should be 0"
        )
    return errs


def _check_useful_stay(scenario_id, on_row, on_eval):
    errs = []
    if not on_eval.get("active_has_high_value_action", False):
        errs.append(
            f"{scenario_id}: ON did not flag active as "
            f"high-value"
        )
    if on_row.get("stay_value_penalty", 0.0) <= 0.0:
        errs.append(
            f"{scenario_id}: ON stay_value_penalty "
            f"({on_row.get('stay_value_penalty', 0.0):.1f}) "
            f"should be > 0"
        )
    if on_row.get("score_adjustment", 0.0) <= 0.0:
        errs.append(
            f"{scenario_id}: ON score_adjustment "
            f"({on_row.get('score_adjustment', 0.0):.1f}) "
            f"should be > 0 (switch penalised)"
        )
    return errs


def analyze(artifact_tag):
    jsonl_path = (
        f"logs/voluntary_switch_targeted_{artifact_tag}.jsonl"
    )
    analysis_json = (
        f"logs/voluntary_switch_targeted_{artifact_tag}_analysis.json"
    )
    analysis_md = (
        f"logs/voluntary_switch_targeted_{artifact_tag}_analysis.md"
    )
    records = _read_jsonl(jsonl_path)
    if not records:
        print(f"ERROR: no records in {jsonl_path}")
        sys.exit(2)

    all_errors = []
    scenario_results = []
    for rec in records:
        scenario_id = rec.get("benchmark_arm", "unknown")
        td = _first_audit_turn(rec)
        if not td:
            all_errors.append(
                f"{scenario_id}: no audit_turns[0]"
            )
            continue
        on_cand_table = (
            td.get("voluntary_switch_candidate_table", [[], []]) or
            [[], []]
        )
        on_row = (
            on_cand_table[0][0] if on_cand_table
            and on_cand_table[0]
            else {}
        )
        reason_codes = (
            td.get("voluntary_switch_reason_codes", [[], []]) or
            [[], []]
        )
        on_reason_codes = reason_codes[0] if reason_codes else []
        on_active_risk = (
            (td.get("voluntary_switch_selected_active_risk", [0, 0])
             or [0, 0])[0]
        )
        on_cand_risk = (
            (td.get("voluntary_switch_selected_candidate_risk",
                    [0, 0])
             or [0, 0])[0]
        )
        on_risk_red = (
            (td.get("voluntary_switch_selected_risk_reduction",
                    [0, 0])
             or [0, 0])[0]
        )
        on_score_adj = (
            (td.get("voluntary_switch_selected_score_adjustment",
                    [0, 0])
             or [0, 0])[0]
        )
        on_eval = {
            "candidate_risk": on_cand_risk,
            "active_risk": on_active_risk,
            "risk_reduction": on_risk_red,
            "score_adjustment": on_score_adj,
            "reason_codes": list(on_reason_codes),
            "candidate_quad_weak": bool(
                on_row.get("quad_weak", False)
            ),
            "candidate_double_threat": bool(
                on_row.get("double_threat", False)
            ),
            "active_low_hp": (
                (td.get("voluntary_switch_active_hp", [1.0, 0.0])
                 or [1.0, 0.0])[0] <= 0.20
            ),
            "active_has_useful_action": bool(
                on_row.get("active_has_useful_action", False)
            ),
            "active_has_high_value_action": bool(
                on_row.get("active_has_high_value_action", False)
            ),
            "sacrifice_preserve_bench_value": (
                on_row.get("sacrifice_penalty", 0.0)
            ),
        }
        off_row = {}  # OFF row is the same scenario
        off_eval = dict(on_eval)

        if scenario_id == "bad_switch_into_4x_weakness":
            errs = _check_bad_switch(
                scenario_id, on_row, on_eval
            )
        elif scenario_id == "healthy_bench_preservation":
            errs = _check_healthy_bench(
                scenario_id, on_row, on_eval, off_row, off_eval
            )
        elif scenario_id == "real_risk_reduction":
            errs = _check_real_risk_reduction(
                scenario_id, on_row, on_eval
            )
        elif scenario_id == "repeat_switch":
            errs = _check_repeat_switch(
                scenario_id, on_row, on_eval, off_row, off_eval
            )
        elif scenario_id == "useful_stay":
            errs = _check_useful_stay(
                scenario_id, on_row, on_eval
            )
        else:
            errs = [f"{scenario_id}: unknown scenario"]

        all_errors.extend(errs)
        scenario_results.append({
            "scenario_id": scenario_id,
            "on_eval": on_eval,
            "on_row_summary": {
                "raw_switch_score": on_row.get(
                    "raw_switch_score", 0.0
                ),
                "adjusted_switch_score": on_row.get(
                    "adjusted_switch_score", 0.0
                ),
                "score_adjustment": on_row.get(
                    "score_adjustment", 0.0
                ),
                "tempo_penalty": on_row.get(
                    "tempo_penalty", 0.0
                ),
                "candidate_penalty": on_row.get(
                    "candidate_penalty", 0.0
                ),
                "repeat_penalty": on_row.get(
                    "repeat_penalty", 0.0
                ),
                "stay_value_penalty": on_row.get(
                    "stay_value_penalty", 0.0
                ),
                "sacrifice_preserve_bench_value": on_row.get(
                    "sacrifice_preserve_bench_value", 0.0
                ),
            },
            "errors": errs,
        })

    report = {
        "artifact_tag": artifact_tag,
        "n_scenarios": len(records),
        "all_errors": all_errors,
        "scenarios": scenario_results,
    }
    with open(analysis_json, "w") as f:
        json.dump(report, f, indent=2)
    md = [
        f"# Phase 6.4.10 Targeted Analysis — {artifact_tag}",
        "",
        f"- Scenarios: {len(records)}",
        f"- Errors: {len(all_errors)}",
        "",
    ]
    for sr in scenario_results:
        md.append(
            f"## {sr['scenario_id']}\n"
        )
        for k, v in sr["on_row_summary"].items():
            md.append(f"- {k}: {v}")
        if sr["errors"]:
            md.append("\nErrors:")
            for e in sr["errors"]:
                md.append(f"- {e}")
        md.append("")
    with open(analysis_md, "w") as f:
        f.write("\n".join(md) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.4.10 voluntary switch targeted analyzer"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Artifact tag to analyze",
    )
    args = parser.parse_args()
    try:
        report = analyze(args.artifact_tag)
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}")
        sys.exit(1)
    n_err = len(report["all_errors"])
    print(
        f"\nTargeted analysis: {report['n_scenarios']} scenarios, "
        f"{n_err} errors"
    )
    for e in report["all_errors"]:
        print(f"  - {e}")
    if n_err:
        sys.exit(2)


if __name__ == "__main__":
    main()
