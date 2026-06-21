"""PLANNER-REPORT-1 — Intent Audit Dashboard.

Read-only summary of all PLANNER artifacts.
"""
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

SCENARIO_DATASET = "logs/planner_dataset_v1.jsonl"
DRYRUN_DATASET = "logs/planner_intent_dryrun_v1.jsonl"
MIXED_DATASET = "logs/planner_mixed_stability_v1.jsonl"
# Path("logs").glob takes patterns relative to "logs", so the
# prefix "logs/" must NOT be in the pattern itself.
RUNTIME_SMOKE_GLOB = "vgc2026_phasePLANNER_IMPL_2b_*_treatment_audit.jsonl"

ALL_INTENTS = [
    "NO_INTENT",
    "ANTI_TRICK_ROOM",
    "ANTI_TAILWIND",
    "ANTI_STAT_BOOST",
    "SPREAD_DEFENSE",
]


def load_jsonl(path):
    records = []
    errors = []
    if not Path(path).exists():
        return records, ["file not found"]
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"line {line_num}: {e}")
    return records, errors


def load_runtime_smoke():
    records = []
    errors = []
    files = sorted(Path("logs").glob(RUNTIME_SMOKE_GLOB))
    for f in files:
        recs, errs = load_jsonl(str(f))
        records.extend(recs)
        if errs:
            errors.append(f"{f.name}: {errs}")
    return records, errors, len(files)


def extract_dataset_v1(row):
    return {
        "intent": row.get("intent_label"),
        "source": row.get("source", "scenario"),
    }


def extract_mixed_v1(row):
    return {
        "intent": row.get("predicted_intent"),
        "evidence_source": row.get("evidence", {}).get("source", ""),
        "matched_moves": row.get("matched_moves", []),
        "source": row.get("source", ""),
    }


def extract_runtime_smoke(rec, turn):
    snap = turn.get("state_snapshot", {}) or {}
    return {
        "intent": snap.get("planner_intent_label"),
        "confidence": snap.get("planner_intent_confidence"),
        "evidence_source": snap.get("planner_intent_evidence_source"),
        "matched_moves": snap.get("planner_intent_matched_moves") or [],
        "routed_to_policy": snap.get("planner_intent_routed_to_policy"),
        "benchmark_arm": rec.get("benchmark_arm", "?"),
    }


def compute_intent_distribution(records, key="intent"):
    counts = Counter()
    for r in records:
        intent = r.get(key)
        if intent is None:
            intent = "MISSING"
        counts[intent] += 1
    return {intent: counts.get(intent, 0) for intent in ALL_INTENTS + ["MISSING"]}


def compute_confidence_buckets(records):
    buckets = Counter()
    for r in records:
        c = r.get("confidence")
        if c is None:
            buckets["N/A"] += 1
        elif c == 0.0:
            buckets["0.0 (NO_INTENT)"] += 1
        elif c < 0.7:
            buckets["0.5-0.65 (low)"] += 1
        elif c < 0.9:
            buckets["0.7-0.85 (mid)"] += 1
        else:
            buckets["0.9+ (high)"] += 1
    return dict(buckets)


def compute_evidence_source_distribution(records):
    counts = Counter()
    for r in records:
        ev = r.get("evidence_source") or "MISSING"
        counts[ev] += 1
    return dict(counts.most_common())


def compute_matched_moves_top(records, n=15):
    counts = Counter()
    for r in records:
        for m in r.get("matched_moves") or []:
            counts[m] += 1
    return dict(counts.most_common(n))


def compute_no_intent_ratio(records, key="intent"):
    if not records:
        return 0.0
    n_no = sum(1 for r in records if r.get(key) in ("NO_INTENT", None, "MISSING"))
    return n_no / len(records)


def compute_real_positives(records, real_source_pattern="real"):
    counts = {intent: 0 for intent in ALL_INTENTS}
    for r in records:
        src = r.get("source", "")
        if not src.startswith(real_source_pattern):
            continue
        intent = r.get("intent")
        if intent in counts and intent != "NO_INTENT":
            counts[intent] += 1
    return counts


def build_dashboard():
    dashboard = {
        "version": "v1",
        "summary": {},
        "per_source": {},
        "recommendation": {},
    }

    scen_records, scen_errors = load_jsonl(SCENARIO_DATASET)
    scen_intent_records = [extract_dataset_v1(r) for r in scen_records]
    dashboard["per_source"]["scenario_dataset"] = {
        "path": SCENARIO_DATASET,
        "total_rows": len(scen_records),
        "parse_errors": scen_errors,
        "intent_distribution": compute_intent_distribution(scen_intent_records),
        "no_intent_ratio": compute_no_intent_ratio(scen_intent_records),
    }

    dry_records, dry_errors = load_jsonl(DRYRUN_DATASET)
    dry_intent_records = [extract_dataset_v1(r) for r in dry_records]
    dashboard["per_source"]["dryrun_dataset"] = {
        "path": DRYRUN_DATASET,
        "total_rows": len(dry_records),
        "parse_errors": dry_errors,
        "intent_distribution": compute_intent_distribution(dry_intent_records),
        "no_intent_ratio": compute_no_intent_ratio(dry_intent_records),
    }

    mixed_records, mixed_errors = load_jsonl(MIXED_DATASET)
    mixed_intent_records = [extract_mixed_v1(r) for r in mixed_records]
    mixed_by_source = defaultdict(list)
    for r in mixed_intent_records:
        src = r.get("source", "unknown")
        mixed_by_source[src].append(r)
    dashboard["per_source"]["mixed_dataset"] = {
        "path": MIXED_DATASET,
        "total_rows": len(mixed_records),
        "parse_errors": mixed_errors,
        "sources": {
            src: {
                "rows": len(rs),
                "intent_distribution": compute_intent_distribution(rs),
                "no_intent_ratio": compute_no_intent_ratio(rs),
            }
            for src, rs in mixed_by_source.items()
        },
    }

    smoke_records, smoke_errors, n_files = load_runtime_smoke()
    smoke_turn_records = []
    smoke_on_records = []
    for rec in smoke_records:
        for turn in rec.get("audit_turns", []):
            extracted = extract_runtime_smoke(rec, turn)
            smoke_turn_records.append(extracted)
            if rec.get("benchmark_arm") == "on":
                smoke_on_records.append(extracted)
    dashboard["per_source"]["runtime_smoke"] = {
        "glob": RUNTIME_SMOKE_GLOB,
        "n_files": n_files,
        "total_battles": len(smoke_records),
        "total_turns": len(smoke_turn_records),
        "total_turns_on_arm": len(smoke_on_records),
        "parse_errors": smoke_errors,
        "intent_distribution": compute_intent_distribution(smoke_turn_records),
        "no_intent_ratio": compute_no_intent_ratio(smoke_turn_records),
        "confidence_buckets": compute_confidence_buckets(smoke_on_records),
        "evidence_source_distribution": compute_evidence_source_distribution(smoke_on_records),
        "matched_moves_top": compute_matched_moves_top(smoke_on_records),
    }

    real_positives_mixed = compute_real_positives(mixed_intent_records)
    real_positives_runtime_smoke_on = {
        intent: compute_intent_distribution(smoke_on_records).get(intent, 0)
        for intent in ALL_INTENTS
    }
    real_positives_runtime_smoke_on["NO_INTENT"] = 0

    combined_real = {intent: 0 for intent in ALL_INTENTS}
    for intent, n in real_positives_mixed.items():
        combined_real[intent] += n
    for intent, n in real_positives_runtime_smoke_on.items():
        if intent != "NO_INTENT":
            combined_real[intent] += n

    dashboard["real_positives"] = {
        "mixed_dataset_real": real_positives_mixed,
        "runtime_smoke_on_arm": real_positives_runtime_smoke_on,
        "combined": combined_real,
    }

    real_fires_by_intent = {k: v for k, v in combined_real.items() if k != "NO_INTENT"}
    sorted_intents = sorted(real_fires_by_intent.items(), key=lambda x: -x[1])

    n_mixed_real_turns = sum(
        v["rows"] for k, v in dashboard["per_source"]["mixed_dataset"]["sources"].items()
        if k.startswith("real")
    )
    n_smoke_on_turns = len(smoke_on_records)
    n_real_turns = n_mixed_real_turns + n_smoke_on_turns

    if sorted_intents and sorted_intents[0][1] > 0:
        top_intent, top_count = sorted_intents[0]
        fire_rate = top_count / n_real_turns if n_real_turns else 0
        verdict = (
            f"REPORT_READY: {top_intent} has {top_count} real positives "
            f"({fire_rate:.1%} of {n_real_turns} real turns). "
            f"Sufficient signal to consider narrow scoring design."
            if top_count >= 20
            else f"REPORT_READY: {top_intent} has only {top_count} real positives "
            f"({fire_rate:.1%} of {n_real_turns} real turns). "
            f"Keep collecting data; scoring not yet warranted."
        )
    else:
        top_intent = "N/A"
        top_count = 0
        fire_rate = 0.0
        verdict = "REPORT_READY: no real-data fires yet. Keep collecting data."

    dashboard["recommendation"] = {
        "top_intent": top_intent,
        "top_count": top_count,
        "total_real_turns": n_real_turns,
        "fire_rate": fire_rate,
        "all_intents": dict(sorted_intents),
        "verdict": verdict,
    }

    dashboard["summary"] = {
        "scenario_rows": len(scen_records),
        "dryrun_rows": len(dry_records),
        "mixed_rows": len(mixed_records),
        "runtime_smoke_battles": len(smoke_records),
        "runtime_smoke_turns": len(smoke_turn_records),
        "all_intents_covered": sorted(set(
            str(r.get("intent")) for r in scen_intent_records + dry_intent_records
            + mixed_intent_records + smoke_turn_records
            if r.get("intent") is not None
        )),
    }
    return dashboard


def render_markdown(dashboard, md_path):
    lines = []
    lines.append("# PLANNER Intent Audit Dashboard (v1)")
    lines.append("")
    lines.append("**Scope**: read-only summary of all PLANNER artifacts")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    s = dashboard["summary"]
    lines.append(f"- Scenario dataset rows: **{s['scenario_rows']}**")
    lines.append(f"- Dry-run dataset rows: **{s['dryrun_rows']}**")
    lines.append(f"- Mixed stability rows: **{s['mixed_rows']}**")
    lines.append(f"- Runtime smoke battles: **{s['runtime_smoke_battles']}** "
                 f"({s['runtime_smoke_turns']} turns)")
    lines.append(f"- All intents observed: `{s['all_intents_covered']}`")
    lines.append("")

    lines.append("## Per-source distribution")
    lines.append("")

    def render_source(name, info):
        ls = []
        ls.append(f"### {name}")
        ls.append("")
        if "path" in info:
            ls.append(f"- File: `{info['path']}`")
        if "glob" in info:
            ls.append(f"- Glob: `{info['glob']}`")
            ls.append(f"- Files matched: {info['n_files']}")
        if "total_battles" in info:
            ls.append(f"- Battles: {info['total_battles']}")
            ls.append(f"- Turns: {info['total_turns']}")
            ls.append(f"- ON arm turns: {info.get('total_turns_on_arm', 'N/A')}")
        if "total_rows" in info:
            ls.append(f"- Rows: {info['total_rows']}")
        if info.get("parse_errors"):
            ls.append(f"- Parse errors: {info['parse_errors']}")
        if "sources" in info:
            ls.append("")
            ls.append("| source | rows | NO_INTENT ratio | intent dist |")
            ls.append("|---|---|---|---|")
            for src, s in info["sources"].items():
                no_r = s["no_intent_ratio"]
                dist = ", ".join(
                    f"{k}:{v}" for k, v in s["intent_distribution"].items() if v > 0
                )
                ls.append(f"| `{src}` | {s['rows']} | {no_r:.1%} | {dist} |")
        else:
            ls.append("")
            ls.append("| intent | count |")
            ls.append("|---|---|")
            for intent, count in info["intent_distribution"].items():
                ls.append(f"| `{intent}` | {count} |")
            ls.append("")
            ls.append(f"- NO_INTENT ratio: **{info['no_intent_ratio']:.1%}**")
        if "confidence_buckets" in info:
            ls.append("")
            ls.append("**Confidence buckets (ON arm)**:")
            ls.append("")
            for bucket, count in info["confidence_buckets"].items():
                ls.append(f"- `{bucket}`: {count}")
        if "evidence_source_distribution" in info:
            ls.append("")
            ls.append("**Evidence sources (ON arm)**:")
            ls.append("")
            for ev, count in info["evidence_source_distribution"].items():
                ls.append(f"- `{ev}`: {count}")
        if "matched_moves_top" in info:
            ls.append("")
            ls.append("**Top matched moves (ON arm)**:")
            ls.append("")
            for mv, count in list(info["matched_moves_top"].items())[:10]:
                ls.append(f"- `{mv}`: {count}")
        ls.append("")
        return ls

    for name, info in dashboard["per_source"].items():
        lines.extend(render_source(name, info))

    lines.append("## Real-data positives (non-NO_INTENT fires)")
    lines.append("")
    rp = dashboard["real_positives"]
    lines.append("| intent | mixed_real | smoke_on | combined |")
    lines.append("|---|---|---|---|")
    for intent in ALL_INTENTS:
        if intent == "NO_INTENT":
            continue
        m = rp["mixed_dataset_real"].get(intent, 0)
        s = rp["runtime_smoke_on_arm"].get(intent, 0)
        c = rp["combined"].get(intent, 0)
        lines.append(f"| `{intent}` | {m} | {s} | **{c}** |")
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    rec = dashboard["recommendation"]
    if rec:
        lines.append(f"**Top intent**: `{rec.get('top_intent', 'N/A')}` "
                     f"with {rec.get('top_count', 0)} real positives")
        lines.append(f"**Total real turns audited**: {rec.get('total_real_turns', 0)}")
        lines.append(f"**Fire rate**: {rec.get('fire_rate', 0):.2%}")
        lines.append("")
        lines.append("**All intents by real positive count**:")
        lines.append("")
        for intent, count in rec.get("all_intents", {}).items():
            lines.append(f"- `{intent}`: {count}")
        lines.append("")
        lines.append(f"**Verdict**: {rec.get('verdict', 'N/A')}")
    lines.append("")

    lines.append("## Decision label")
    lines.append("")
    lines.append("`REPORT_READY`")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))


def main():
    dashboard = build_dashboard()
    json_path = "logs/planner_intent_dashboard_v1.json"
    md_path = "logs/planner_intent_dashboard_v1.md"
    with open(json_path, "w") as f:
        json.dump(dashboard, f, indent=2)
    render_markdown(dashboard, md_path)
    print(f"Wrote dashboard: {json_path}")
    print(f"Wrote markdown: {md_path}")
    print()
    s = dashboard["summary"]
    print(f"Summary:")
    print(f"  scenario_rows={s['scenario_rows']}, dryrun_rows={s['dryrun_rows']}")
    print(f"  mixed_rows={s['mixed_rows']}")
    print(f"  smoke_battles={s['runtime_smoke_battles']}, smoke_turns={s['runtime_smoke_turns']}")
    print(f"  intents covered: {s['all_intents_covered']}")
    print()
    if "recommendation" in dashboard and dashboard["recommendation"]:
        rec = dashboard["recommendation"]
        print(f"Recommendation: top={rec['top_intent']}, count={rec['top_count']}, "
              f"fire_rate={rec['fire_rate']:.2%}")
        print(f"Verdict: {rec['verdict']}")


if __name__ == "__main__":
    main()
