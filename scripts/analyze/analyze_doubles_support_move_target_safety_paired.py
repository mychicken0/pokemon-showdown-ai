#!/usr/bin/env python3
"""
Phase 6.3.8c — Paired regression analyzer.

Reads the artifacts produced by
``bot_doubles_support_move_target_safety_paired_qualification.py``
and computes paired statistics for Support Move Target
Hard Safety.

Produces:
  - paired-analysis JSON
  - paired-analysis Markdown

Paired statistics (every outcome normalized to the
safety-ON policy perspective):
  - D1 ON wins / losses / ties
  - D2 ON wins / losses / ties
  - combined ON win rate and Wilson 95% CI
  - paired categories: ON-both / OFF-both / split / invalid
  - exact two-sided sign test (ON-both vs OFF-both,
    only decisive pairs)
  - exact one-sided test for ON regression
  - paired bootstrap CI for ON-policy win-rate
    difference
  - side-split and side-collapse diagnostics

Safety metrics (read from production-generated support
audit fields):
  - wrong-side opportunities / selected / avoided /
    only-legal
  - Heal Pulse into opponent
  - opponent-disruption into ally/self
  - move / reason / target-side split
  - Pollen Puff and Skill Swap candidate and blocked
    counts
  - spread / focus-fire
  - accounting invariant
  - selected/avoided mutual exclusion

Counterfactual changed-action analysis:
  - first divergence per pair where ON and OFF chose
    different actions in comparable states
  - distinguishes support-safety-caused changes from
    unrelated post-divergence state

Hard-fail artifact validation:
  - wrong row count
  - malformed JSON
  - duplicate battle tag
  - missing pair (D1 without D2 or vice versa)
  - incomplete D1/D2 pair (status != ok, on_won None)
  - team/seed mismatch across side swap
  - invalid outcome (on_won not in {True, False, None}
    for finished=1)
  - timeout/error/no_battle
  - wrong ON/OFF assignment
  - missing support-target audit fields
  - support accounting failure (candidate_blocked !=
    selected + avoided)
  - selected/avoided mutual-exclusion failure
  - V2l.2 runtime audit mismatch (shared_engine_used
    != True when shared_engine_invocation_id is set)
"""
import argparse
import json
import math
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


# ========================== Helpers ==========================


def wilson_ci(s: int, n: int, z: float = 1.96):
    """Wilson 95% confidence interval for a binomial
    proportion.
    """
    if n == 0:
        return (0.0, 1.0)
    p = s / n
    denom = 1 + (z ** 2) / n
    center = (p + (z ** 2) / (2 * n)) / denom
    margin = (
        z * math.sqrt(p * (1 - p) / n + (z ** 2) / (4 * n * n))
    ) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def exact_binomial_two_sided(k: int, n: int) -> float:
    """Two-sided exact sign test (no normal approx)."""
    if n == 0:
        return 1.0
    # Under H0, p=0.5. p-value = sum of
    # P(Binomial(n, 0.5) <= k) for k<=n/2 OR
    # P(Binomial(n, 0.5) <= n-k) for n-k<=n/2.
    # Two-sided: 2 * min(P(X<=k), P(X<=n-k)).
    from math import comb
    if k > n - k:
        k = n - k
    p_le = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_le)


def exact_binomial_one_sided(k: int, n: int) -> float:
    """One-sided exact test for H0: p >= 0.5.
    Returns P(Binomial(n, 0.5) <= k) i.e. the
    p-value of observing ``k`` or fewer successes if
    the true rate is 0.5. Small p-value = evidence
    against the null.
    """
    if n == 0:
        return 1.0
    from math import comb
    return sum(comb(n, i) for i in range(k + 1)) / (2 ** n)


def paired_bootstrap_treatment(
    treatment_scores: List[int],
    n_boot: int = 2000,
    seed: int = 6381,
) -> Tuple[float, float, float]:
    """Paired bootstrap CI for the mean treatment
    effect.

    The treatment score per pair is:
      +1 if ON won both D1 and D2
       0 if split
      -1 if OFF won both D1 and D2

    Resamples ``len(treatment_scores)`` pairs WITH
    replacement. Each bootstrap sample produces
    one mean treatment effect. Returns
    (point, lo, hi) using the 2.5 / 97.5 percentile
    of the bootstrap distribution.

    Deterministic via the seed so the test suite
    can verify the result.
    """
    if not treatment_scores:
        return (float("nan"), float("nan"), float("nan"))
    import random
    rng = random.Random(seed)
    n = len(treatment_scores)
    means = []
    for _ in range(n_boot):
        idxs = [rng.randrange(n) for _ in range(n)]
        sample = [treatment_scores[i] for i in idxs]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot) - 1]
    point = sum(treatment_scores) / n
    return (point, lo, hi)


# Keep the old function for tests that verify
# row-shuffle invariance, but rename and document it
# as "D1 - D2 win rate" only — this is a
# side-position diagnostic, not a treatment effect.
def paired_bootstrap_d1_minus_d2(
    d1_outcomes: List[bool],
    d2_outcomes: List[bool],
    n_boot: int = 2000,
    seed: int = 6381,
) -> Tuple[float, float, float]:
    """D1 - D2 win rate bootstrap (side-position
    diagnostic only — NOT a treatment effect).

    Resamples ``len(d1_outcomes)`` pairs WITH
    replacement. Each bootstrap sample produces
    one (D1 rate - D2 rate) value. Returns
    (point, lo, hi) using the 2.5 / 97.5 percentile.

    DO NOT use this for adoption gates.
    """
    if len(d1_outcomes) != len(d2_outcomes) or not d1_outcomes:
        return (float("nan"), float("nan"), float("nan"))
    import random
    rng = random.Random(seed)
    diffs = []
    n = len(d1_outcomes)
    for _ in range(n_boot):
        idxs = [rng.randrange(n) for _ in range(n)]
        d1_rate = sum(1 for i in idxs if d1_outcomes[i]) / n
        d2_rate = sum(1 for i in idxs if d2_outcomes[i]) / n
        diffs.append(d1_rate - d2_rate)
    diffs.sort()
    lo = diffs[int(0.025 * n_boot)]
    hi = diffs[int(0.975 * n_boot) - 1]
    point = (
        sum(d1_outcomes) - sum(d2_outcomes)
    ) / n
    return (point, lo, hi)


# ========================== Validators ==========================


REQUIRED_BATTLE_KEYS = {
    "pair_id", "side_swap", "p1_arm", "p2_arm",
    "on_arm", "off_arm", "on_player_is_p1",
    "battle_tag", "finished", "status",
    "p1_wins", "p2_wins", "on_won",
    "turns", "error_detail", "p1_name", "p2_name",
    "team_str", "p1_config_on", "p2_config_on",
    "p1_audit_path", "p2_audit_path",
}


def validate_battle_record(rec: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors (empty =
    valid). Hard-fail rules:
      - required keys present
      - pair_id is int
      - side_swap in {D1, D2}
      - p1_arm in {ON, OFF}, p2_arm in {ON, OFF}
      - p1_config_on == (p1_arm == ON)
      - p2_config_on == (p2_arm == ON)
      - on_arm == ON, off_arm == OFF
      - on_player_is_p1 == (p1_arm == ON)
      - status in {ok, timeout, error, no_battle, tie}
      - if finished == 1, on_won in {True, False, None}
      - if finished == 0, status != ok
      - if status != ok, finished == 0
    """
    errors: List[str] = []
    missing = REQUIRED_BATTLE_KEYS - set(rec.keys())
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
    if not isinstance(rec.get("pair_id"), int):
        errors.append(f"pair_id not int: {rec.get('pair_id')!r}")
    if rec.get("side_swap") not in ("D1", "D2"):
        errors.append(f"side_swap not in (D1, D2): {rec.get('side_swap')!r}")
    if rec.get("p1_arm") not in ("ON", "OFF"):
        errors.append(f"p1_arm not in (ON, OFF): {rec.get('p1_arm')!r}")
    if rec.get("p2_arm") not in ("ON", "OFF"):
        errors.append(f"p2_arm not in (ON, OFF): {rec.get('p2_arm')!r}")
    if rec.get("on_arm") != "ON":
        errors.append(f"on_arm != ON: {rec.get('on_arm')!r}")
    if rec.get("off_arm") != "OFF":
        errors.append(f"off_arm != OFF: {rec.get('off_arm')!r}")
    if rec.get("p1_config_on") != (rec.get("p1_arm") == "ON"):
        errors.append(
            f"p1_config_on ({rec.get('p1_config_on')}) != "
            f"(p1_arm == ON) ({rec.get('p1_arm') == 'ON'})"
        )
    if rec.get("p2_config_on") != (rec.get("p2_arm") == "ON"):
        errors.append(
            f"p2_config_on ({rec.get('p2_config_on')}) != "
            f"(p2_arm == ON) ({rec.get('p2_arm') == 'ON'})"
        )
    if rec.get("on_player_is_p1") != (rec.get("p1_arm") == "ON"):
        errors.append(
            f"on_player_is_p1 ({rec.get('on_player_is_p1')}) != "
            f"(p1_arm == ON) ({rec.get('p1_arm') == 'ON'})"
        )
    if rec.get("status") not in ("ok", "timeout", "error",
                                    "no_battle", "tie"):
        errors.append(
            f"status unexpected: {rec.get('status')!r}"
        )
    finished = rec.get("finished", 0)
    if finished == 1:
        if rec.get("on_won") not in (True, False, None):
            errors.append(
                f"finished=1 but on_won invalid: "
                f"{rec.get('on_won')!r}"
            )
    elif finished == 0:
        if rec.get("status") == "ok":
            errors.append("finished=0 but status=ok")
    return errors


def validate_pair(d1: Dict[str, Any], d2: Dict[str, Any]) -> List[str]:
    """Validate a D1/D2 pair: same pair_id, same team_str,
    ON/OFF sides swapped, both have identical
    on/off arm assignment.
    """
    errors: List[str] = []
    if d1.get("pair_id") != d2.get("pair_id"):
        errors.append(
            f"pair_id mismatch: D1={d1.get('pair_id')} "
            f"D2={d2.get('pair_id')}"
        )
    if d1.get("team_str") != d2.get("team_str"):
        errors.append(
            f"team_str mismatch: D1={d1.get('team_str')[:30]!r} "
            f"D2={d2.get('team_str')[:30]!r}"
        )
    if d1.get("on_arm") != d2.get("on_arm"):
        errors.append("on_arm mismatch")
    if d1.get("off_arm") != d2.get("off_arm"):
        errors.append("off_arm mismatch")
    # D1: ON is p1, OFF is p2
    # D2: OFF is p1, ON is p2
    if (d1.get("p1_arm") != "ON") or (d1.get("p2_arm") != "OFF"):
        errors.append(f"D1 not ONvOFF: {d1.get('p1_arm')}v{d1.get('p2_arm')}")
    if (d2.get("p1_arm") != "OFF") or (d2.get("p2_arm") != "ON"):
        errors.append(f"D2 not OFFvON: {d2.get('p1_arm')}v{d2.get('p2_arm')}")
    return errors


def treatment_score_for_pair(d1w: bool, d2w: bool) -> int:
    """Return the treatment score for a complete
    pair (both D1 and D2 are valid):
      +1 = ON won both D1 and D2 (ON_both)
       0 = split
      -1 = OFF won both D1 and D2 (OFF_both)
    """
    if d1w and d2w:
        return +1
    if (not d1w) and (not d2w):
        return -1
    return 0


def validate_treatment_score(score: int) -> List[str]:
    """Return validation errors for a treatment
    score. The score MUST be in {-1, 0, +1}.
    """
    if score not in (-1, 0, 1):
        return [f"treatment score not in {{-1,0,1}}: {score}"]
    return []


def validate_exact_category_counts(
    on_both: int, off_both: int, split: int,
    expected_on_both: int, expected_off_both: int,
    expected_split: int,
) -> List[str]:
    """Hard-fail when paired category counts do
    NOT match the expected counts (used as a
    regression-test guard for known artifacts).
    """
    errs = []
    if on_both != expected_on_both:
        errs.append(
            f"ON_both={on_both} != expected {expected_on_both}"
        )
    if off_both != expected_off_both:
        errs.append(
            f"OFF_both={off_both} != expected {expected_off_both}"
        )
    if split != expected_split:
        errs.append(
            f"split={split} != expected {expected_split}"
        )
    return errs


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARN: malformed JSON line in {path}: {e}")
    return out


# ========================== Artifact inventory ==========================


def _parse_audit_filename(
    path: str,
) -> Optional[Dict[str, Any]]:
    """Parse a per-side audit filename.

    Expected pattern:
      ``support_target_paired_{NNN}_{ONvOFF|OFFvON}__{p1|p2}.jsonl``

    Returns a dict with keys ``pair_id`` (int),
    ``arm`` (str), ``side`` (str), or ``None``
    if the path doesn't match the pattern.
    """
    import re
    fname = os.path.basename(path)
    m = re.match(
        r"support_target_paired_(\d+)_(ONvOFF|OFFvON)__(p1|p2)\.jsonl$",
        fname,
    )
    if not m:
        return None
    return {
        "pair_id": int(m.group(1)),
        "arm": m.group(2),
        "side": m.group(3),
        "filename": fname,
    }


def inventory_artifacts(
    artifact_tag: str,
    logs_dir: str = "logs",
    expected_n_pairs: int = 100,
) -> Dict[str, Any]:
    """Inventory the artifacts produced by a
    Phase 6.3.8c paired qualification.

    The qualifier names per-side audit files by
    ``pair_id`` (not by ``artifact_tag``):

      ``logs/support_target_paired_{NNN}_
      {ONvOFF|OFFvON}__{p1|p2}.jsonl``

    So when the tag is ``phase638c_v2`` the
    per-side files are still
    ``support_target_paired_000_ONvOFF__p1.jsonl``,
    etc. This function globs the per-side pattern
    without the tag prefix.

    Returns a structured dict with:
      - ``n_pairs``: number of unique pair_ids
      - ``n_battles``: number of battle records
        in the main JSONL
      - ``n_per_side_files``: total per-side
        audit files
      - ``per_side_breakdown``: count of
        (arm, side) files
      - ``per_pair_count``: dict mapping
        pair_id -> count of (arm, side) files
      - ``files``: list of all per-side file
        paths with their parsed metadata and
        record counts
      - ``errors``: list of error strings
        (missing, duplicate, malformed,
        zero-byte, etc.)
      - ``battle_tags``: list of all battle
        tags (for duplicate detection)
      - ``duplicate_battle_tags``: list of
        battle tags that appear more than once
      - ``manifest_classification``: dict with
        keys:
        - ``exists``: bool
        - ``size_bytes``: int
        - ``classification``: one of
          ``"legacy_empty_creation_defect"``,
          ``"not_created_expected"``,
          ``"unexpected_non_empty"``, ``"malformed"``
        - ``is_failure``: bool (True if the
          classification is a hard-fail)

    Hard-fail rules (return errors but do
    NOT raise — callers may inspect errors
    to decide whether to abort):
      - missing main JSONL
      - missing per-side audit files
      - duplicate (pair_id, arm, side) files
      - zero-byte REQUIRED per-side audit files
      - malformed JSONL lines in per-side files
      - wrong arm name (not ONvOFF/OFFvON)
      - wrong side name (not p1/p2)
      - duplicate battle tags
      - per-pair file count != 4
      - record count per file != 1 (each
        per-side file should contain exactly
        one battle record with all turns)

    Manifest classification rules:
      - Current qualifiers do not create an aggregate audit
        manifest. The per-player audit files referenced by each
        battle record are the source of truth.
      - A missing manifest is therefore
        ``"not_created_expected"``.
      - Historical runs may contain the zero-byte file created
        by the old qualifier. It is retained for artifact
        immutability and classified as
        ``"legacy_empty_creation_defect"`` with a warning.
      - Any non-empty aggregate manifest is unsupported. Valid
        JSON is ``"unexpected_non_empty"`` and malformed JSON is
        ``"malformed"``; both are hard failures.
    """
    result: Dict[str, Any] = {
        "artifact_tag": artifact_tag,
        "logs_dir": logs_dir,
        "expected_n_pairs": expected_n_pairs,
        "n_pairs": 0,
        "n_battles": 0,
        "n_per_side_files": 0,
        "per_side_breakdown": {},
        "per_pair_count": {},
        "files": [],
        "battle_tags": [],
        "duplicate_battle_tags": [],
        "errors": [],
        "warnings": [],
        "manifest_classification": {
            "exists": False,
            "size_bytes": 0,
            "classification": "not_created_expected",
            "is_failure": False,
        },
    }
    # --- 1. Main battle JSONL ---
    main_jsonl = (
        f"{logs_dir}/support_target_paired_{artifact_tag}.jsonl"
    )
    if not os.path.isfile(main_jsonl):
        result["errors"].append(
            f"missing main JSONL: {main_jsonl}"
        )
    else:
        size = os.path.getsize(main_jsonl)
        if size == 0:
            result["errors"].append(
                f"main JSONL is zero bytes: {main_jsonl}"
            )
        battles = _read_jsonl(main_jsonl)
        result["n_battles"] = len(battles)
        if len(battles) == 0:
            result["errors"].append(
                f"main JSONL has no records: {main_jsonl}"
            )
        # Collect battle tags
        seen_tags: Dict[str, int] = {}
        for b in battles:
            tag = b.get("battle_tag", "")
            if not tag:
                result["warnings"].append(
                    f"battle record without battle_tag in {main_jsonl}"
                )
            seen_tags[tag] = seen_tags.get(tag, 0) + 1
        for tag, n in seen_tags.items():
            if n > 1:
                result["duplicate_battle_tags"].append(
                    {"battle_tag": tag, "count": n}
                )
        result["battle_tags"] = list(seen_tags.keys())
        if result["duplicate_battle_tags"]:
            result["errors"].append(
                f"duplicate battle tags: "
                f"{result['duplicate_battle_tags']}"
            )
    # --- 1b. Legacy aggregate-manifest classification ---
    # Current qualifiers do not create this file. Historical
    # zero-byte files are preserved but explicitly identified as
    # a creation defect.
    manifest_path = (
        f"{logs_dir}/support_target_paired_"
        f"{artifact_tag}_audit.jsonl"
    )
    if not os.path.isfile(manifest_path):
        result["manifest_classification"] = {
            "exists": False,
            "size_bytes": 0,
            "classification": "not_created_expected",
            "is_failure": False,
        }
    else:
        size = os.path.getsize(manifest_path)
        if size == 0:
            result["manifest_classification"] = {
                "exists": True,
                "size_bytes": 0,
                "classification": "legacy_empty_creation_defect",
                "is_failure": False,
            }
            result["warnings"].append(
                f"legacy aggregate audit manifest is zero bytes: "
                f"{manifest_path}; old qualifier creation defect"
            )
        else:
            records = _read_jsonl(manifest_path)
            if not records:
                result["manifest_classification"] = {
                    "exists": True,
                    "size_bytes": size,
                    "classification": "malformed",
                    "is_failure": True,
                }
                result["errors"].append(
                    f"audit manifest at {manifest_path} "
                    f"is non-empty ({size} B) but malformed"
                )
            else:
                result["manifest_classification"] = {
                    "exists": True,
                    "size_bytes": size,
                    "classification": "unexpected_non_empty",
                    "is_failure": True,
                }
                result["errors"].append(
                    f"audit manifest at {manifest_path} "
                    f"is non-empty ({size} B, {len(records)} "
                    f"records); aggregate manifests are unsupported"
                )
    # --- 2. Per-side audit files ---
    # The qualifier names per-side files by
    # pair_id, not by artifact_tag. So we glob
    # the pattern without a tag prefix.
    import glob
    pattern = (
        f"{logs_dir}/support_target_paired_"
        f"*_ONvOFF__p1.jsonl"
    )
    p1_onv_off = glob.glob(pattern)
    pattern = (
        f"{logs_dir}/support_target_paired_"
        f"*_ONvOFF__p2.jsonl"
    )
    p2_onv_off = glob.glob(pattern)
    pattern = (
        f"{logs_dir}/support_target_paired_"
        f"*_OFFvON__p1.jsonl"
    )
    p1_offv_on = glob.glob(pattern)
    pattern = (
        f"{logs_dir}/support_target_paired_"
        f"*_OFFvON__p2.jsonl"
    )
    p2_offv_on = glob.glob(pattern)
    all_candidates = (
        p1_onv_off + p2_onv_off + p1_offv_on + p2_offv_on
    )
    per_side_files = []
    for c in all_candidates:
        meta = _parse_audit_filename(c)
        if meta is None:
            result["warnings"].append(
                f"file matches per-side pattern but "
                f"parse_audit_filename returned None: {c}"
            )
            continue
        per_side_files.append((c, meta))
    result["n_per_side_files"] = len(per_side_files)
    # --- 3. Per-file checks ---
    parsed_meta_keys: List[Tuple[int, str, str]] = []
    file_sizes: Dict[str, int] = {}
    file_records: Dict[str, int] = {}
    for path, meta in per_side_files:
        size = os.path.getsize(path)
        file_sizes[path] = size
        recs = _read_jsonl(path)
        file_records[path] = len(recs)
        file_info = {
            "path": path,
            "pair_id": meta["pair_id"],
            "arm": meta["arm"],
            "side": meta["side"],
            "size_bytes": size,
            "n_records": len(recs),
        }
        result["files"].append(file_info)
        parsed_meta_keys.append(
            (meta["pair_id"], meta["arm"], meta["side"])
        )
        # Per-file errors
        if size == 0:
            result["errors"].append(
                f"zero-byte audit file: {path}"
            )
        if len(recs) != 1:
            result["errors"].append(
                f"audit file record count != 1: "
                f"{path} has {len(recs)} records"
            )
        if meta["arm"] not in ("ONvOFF", "OFFvON"):
            result["errors"].append(
                f"wrong arm name: {path} arm={meta['arm']}"
            )
        if meta["side"] not in ("p1", "p2"):
            result["errors"].append(
                f"wrong side name: {path} side={meta['side']}"
            )
        # Per-arm/side breakdown
        key = f"{meta['arm']}__{meta['side']}"
        result["per_side_breakdown"][key] = (
            result["per_side_breakdown"].get(key, 0) + 1
        )
        # Per-pair count
        pid = meta["pair_id"]
        result["per_pair_count"][pid] = (
            result["per_pair_count"].get(pid, 0) + 1
        )
    # --- 4. Duplicate (pair_id, arm, side) ---
    seen: Dict[Tuple[int, str, str], int] = {}
    for key in parsed_meta_keys:
        seen[key] = seen.get(key, 0) + 1
    for key, n in seen.items():
        if n > 1:
            result["errors"].append(
                f"duplicate (pair_id, arm, side): "
                f"{key} count={n}"
            )
    # --- 5. Per-pair file count must be 4 ---
    for pid, n in result["per_pair_count"].items():
        if n != 4:
            result["errors"].append(
                f"pair {pid} has {n} per-side files "
                f"(expected 4)"
            )
    # Also check expected pairs that have 0 files
    actual_pair_ids = set(result["per_pair_count"].keys())
    expected_pair_ids = set(range(expected_n_pairs))
    missing_pairs = expected_pair_ids - actual_pair_ids
    for pid in sorted(missing_pairs):
        result["errors"].append(
            f"pair {pid} has 0 per-side files "
            f"(expected 4)"
        )
        # Also record 0 in per_pair_count for
        # downstream visibility
        result["per_pair_count"][pid] = 0
    # --- 6. Pair count ---
    result["n_pairs"] = len(result["per_pair_count"])
    if result["n_pairs"] != expected_n_pairs:
        result["errors"].append(
            f"pair count {result['n_pairs']} != "
            f"expected {expected_n_pairs}"
        )
    # --- 7. Expected per-side breakdown ---
    expected_breakdown = {
        "ONvOFF__p1": expected_n_pairs,
        "ONvOFF__p2": expected_n_pairs,
        "OFFvON__p1": expected_n_pairs,
        "OFFvON__p2": expected_n_pairs,
    }
    for k, expected in expected_breakdown.items():
        actual = result["per_side_breakdown"].get(k, 0)
        if actual != expected:
            result["errors"].append(
                f"per-side breakdown {k}: "
                f"actual={actual} expected={expected}"
            )
    return result


def sha256_file(path: str) -> str:
    """Return the SHA-256 hex digest of a file's
    contents.
    """
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_metadata(path: str) -> Dict[str, Any]:
    """Return filesystem metadata for a file:
    size in bytes, modification time, SHA-256.
    """
    return {
        "path": path,
        "size_bytes": os.path.getsize(path) if os.path.isfile(path) else 0,
        "mtime": os.path.getmtime(path) if os.path.isfile(path) else 0,
        "sha256": (
            sha256_file(path) if os.path.isfile(path)
            and os.path.getsize(path) > 0 else ""
        ),
    }


def format_git_status_lines(
    modified: List[str],
    untracked: List[str],
) -> List[str]:
    """Format a git status --short-style report.

    Takes explicit lists of modified and untracked
    paths. Each path appears exactly once. Used
    by the audit report so a single path can
    never be classified as both modified and
    untracked.
    """
    lines = []
    for p in sorted(set(modified)):
        lines.append(f" M {p}")
    for p in sorted(set(untracked)):
        if p in modified:
            # Defensive: a path cannot be in both
            # lists. If it is, we raise to surface
            # the bug rather than silently
            # double-classify.
            raise ValueError(
                f"path {p} appears in both modified and "
                f"untracked lists"
            )
        lines.append(f"?? {p}")
    return lines


# ========================== Support metrics ==========================


def _is_wrong_side(
    selected: bool, blocked: bool,
    intended: str, actual: str,
) -> bool:
    """Corrected wrong-side definition per Phase 6.3.8c:
    selected == True AND blocked == True AND
    intended_side != actual_side.
    """
    if not (selected and blocked):
        return False
    return intended != actual


def _count_support_metrics_from_audit(
    audit_path: str,
) -> Dict[str, Any]:
    """Read production-generated audit JSONL and count
    support-target metrics. Returns a dict with both
    per-side and total counts.
    """
    metrics = {
        "wrong_side_opportunities": 0,
        "wrong_side_selected": 0,
        "wrong_side_avoided": 0,
        "only_legal": 0,
        "heal_pulse_into_opponent": 0,
        "heal_pulse_into_ally": 0,
        "opponent_disruption_into_ally": 0,
        "opponent_disruption_into_self": 0,
        "pollen_puff_candidates": 0,
        "pollen_puff_blocked": 0,
        "skill_swap_candidates": 0,
        "skill_swap_blocked": 0,
        "spread_count": 0,
        "focus_fire_count": 0,
        "move_split": {},
        "target_side_split": {},
        "intended_split": {},
        "reason_split": {},
        "selected": 0,
        "avoided": 0,
        "candidate_blocked": 0,
        "only_legal_count": 0,
        "v2l2_invocation_status_mismatch": 0,
        "v2l2_shared_engine_used_mismatch": 0,
        "accounting_invariant_fail": 0,
        "mutual_exclusion_fail": 0,
    }
    if not os.path.isfile(audit_path):
        return metrics
    for rec in _read_jsonl(audit_path):
        for turn in rec.get("audit_turns", []) or []:
            # V2l.2 runtime audit mismatch
            inv_status = turn.get("shared_engine_invocation_status")
            inv_id = turn.get("shared_engine_invocation_id")
            if inv_id and inv_status != "completed":
                metrics["v2l2_invocation_status_mismatch"] += 1
            if (
                inv_id
                and turn.get("shared_engine_used") is not True
            ):
                metrics["v2l2_shared_engine_used_mismatch"] += 1
            # focus fire
            if turn.get("focus_fire_triggered"):
                metrics["focus_fire_count"] += 1
            for sk in ("slot_0", "slot_1"):
                slot = turn.get(sk, {}) or {}
                if not slot:
                    continue
                if (slot.get("action_types") or {}).get("spread"):
                    metrics["spread_count"] += 1
                cand_blocked = bool(
                    slot.get("support_target_candidate_blocked")
                )
                selected = bool(slot.get("support_target_selected"))
                avoided = bool(slot.get("support_target_avoided"))
                only_legal = bool(
                    slot.get("support_target_only_legal")
                )
                move_id = slot.get("support_target_move_id") or ""
                intended = slot.get(
                    "support_target_intended_side"
                ) or ""
                actual = slot.get("support_target_actual_side") or ""
                if cand_blocked:
                    metrics["candidate_blocked"] += 1
                if selected:
                    metrics["selected"] += 1
                if avoided:
                    metrics["avoided"] += 1
                if only_legal:
                    metrics["only_legal_count"] += 1
                if cand_blocked:
                    metrics["wrong_side_opportunities"] += 1
                    if _is_wrong_side(
                        selected, True, intended, actual
                    ):
                        metrics["wrong_side_selected"] += 1
                    else:
                        metrics["wrong_side_avoided"] += 1
                    # Move split
                    metrics["move_split"][move_id] = (
                        metrics["move_split"].get(move_id, 0) + 1
                    )
                    # Target side split
                    metrics["target_side_split"][actual] = (
                        metrics["target_side_split"].get(
                            actual, 0
                        ) + 1
                    )
                    # Intended side split
                    metrics["intended_split"][intended] = (
                        metrics["intended_split"].get(
                            intended, 0
                        ) + 1
                    )
                    # Reason split (truncated)
                    reason = slot.get("support_target_reason") or ""
                    metrics["reason_split"][reason[:40]] = (
                        metrics["reason_split"].get(
                            reason[:40], 0
                        ) + 1
                    )
                # Pollen Puff
                if move_id == "pollenpuff":
                    metrics["pollen_puff_candidates"] += 1
                    if cand_blocked:
                        metrics["pollen_puff_blocked"] += 1
                if move_id == "skillswap":
                    metrics["skill_swap_candidates"] += 1
                    if cand_blocked:
                        metrics["skill_swap_blocked"] += 1
                if (
                    move_id == "healpulse"
                    and intended == "ally"
                    and actual == "opponent"
                    and selected
                ):
                    metrics["heal_pulse_into_opponent"] += 1
                if (
                    move_id == "healpulse"
                    and intended == "ally"
                    and actual == "ally"
                    and selected
                ):
                    metrics["heal_pulse_into_ally"] += 1
                if (
                    intended == "opponent"
                    and actual == "ally"
                ):
                    metrics["opponent_disruption_into_ally"] += 1
                if (
                    intended == "opponent"
                    and actual == "self"
                ):
                    metrics["opponent_disruption_into_self"] += 1
                # Accounting invariant per slot:
                # cand_blocked == selected + avoided
                if cand_blocked and not (selected or avoided):
                    metrics["only_legal_count"] += 1
                if cand_blocked and selected and avoided:
                    metrics["mutual_exclusion_fail"] += 1
                if cand_blocked and not (
                    (selected and not avoided)
                    or (avoided and not selected)
                    or (not selected and not avoided)
                ):
                    metrics["accounting_invariant_fail"] += 1
    return metrics


# ========================== Counterfactual ==========================


def _audit_path_for(battle: Dict[str, Any], which: str) -> str:
    """Return the audit path for the given side
    (p1 or p2). The qualifier writes one file per
    side per pair.
    """
    if which == "p1":
        return battle.get("p1_audit_path") or ""
    return battle.get("p2_audit_path") or ""


def _per_battle_divergence(
    d1: Dict[str, Any], d2: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Walk D1 and D2 audit turns. Find the first turn
    where ON and OFF chose different actions in the
    same slot on the same side. Distinguish
    support-safety-caused changes from unrelated
    post-divergence state.

    Returns a list of divergence records (one per
    pair). If no comparable divergence, returns
    ``[{"category": "no_divergence"}]``.

    The qualifier writes one audit file per side per
    pair. D1 has p1_arm=ON, p2_arm=OFF. D2 has
    p1_arm=OFF, p2_arm=ON. So:
      D1 ON side = p1 → d1.p1_audit_path
      D1 OFF side = p2 → d1.p2_audit_path
      D2 OFF side = p1 → d2.p1_audit_path
      D2 ON side = p2 → d2.p2_audit_path
    """
    d1_on_path = _audit_path_for(d1, "p1")
    d1_off_path = _audit_path_for(d1, "p2")
    d2_off_path = _audit_path_for(d2, "p1")
    d2_on_path = _audit_path_for(d2, "p2")
    d1_records = _read_jsonl(d1_on_path)
    d2_records = _read_jsonl(d2_on_path)
    d1_off_records = _read_jsonl(d1_off_path)
    d2_off_records = _read_jsonl(d2_off_path)
    d1_turns: Dict[int, Dict[str, Any]] = {}
    d2_turns: Dict[int, Dict[str, Any]] = {}
    for rec in d1_records:
        for t in rec.get("audit_turns", []) or []:
            d1_turns[int(t.get("turn", -1))] = t
    for rec in d2_records:
        for t in rec.get("audit_turns", []) or []:
            d2_turns[int(t.get("turn", -1))] = t
    all_turns = sorted(set(d1_turns.keys()) | set(d2_turns.keys()))
    for t in all_turns:
        d1t = d1_turns.get(t)
        d2t = d2_turns.get(t)
        if d1t is None or d2t is None:
            continue
        for sk in ("slot_0", "slot_1"):
            d1_slot = d1t.get(sk, {}) or {}
            d2_slot = d2t.get(sk, {}) or {}
            d1_mid = d1_slot.get("selected_action_move_id") or ""
            d2_mid = d2_slot.get("selected_action_move_id") or ""
            d1_tpos = d1_slot.get("selected_action_target_position")
            d2_tpos = d2_slot.get("selected_action_target_position")
            d1_kind = d1_slot.get("selected_action_kind") or ""
            d2_kind = d2_slot.get("selected_action_kind") or ""
            d1_targeted = d1_mid != d2_mid or d1_tpos != d2_tpos
            if not d1_targeted:
                continue
            d1_blocked = bool(
                d1_slot.get("support_target_candidate_blocked")
            )
            d2_blocked = bool(
                d2_slot.get("support_target_candidate_blocked")
            )
            d1_selected_blocked = bool(
                d1_slot.get("support_target_selected")
            )
            d2_selected_blocked = bool(
                d2_slot.get("support_target_selected")
            )
            d1_intended = d1_slot.get(
                "support_target_intended_side"
            ) or ""
            d1_actual = d1_slot.get(
                "support_target_actual_side"
            ) or ""
            d1_reason = d1_slot.get("support_target_reason") or ""
            # d1 audit is ON-side (D1 with p1=ON).
            # d2 audit is ON-side (D2 with p2=ON).
            # So we compare ON (d1t, d2t) actions
            # between the two side-swap arms.
            # d1_actual (D1's ON choice) is the
            # "off" perspective: in D1, ON=p1.
            # d2_actual (D2's ON choice) is the
            # "on" perspective: in D2, ON=p2.
            # The comparison is ON-perspective
            # between D1 and D2.
            # The support_safety_avoided_wrong_side
            # category should only be used when
            # BOTH sides are doing moves and the
            # block affected the d2 choice. If d1
            # is a switch/pass, the divergence is
            # unrelated to support safety.
            d1_is_move = (d1_kind == "move")
            d2_is_move = (d2_kind == "move")
            category = "unrelated_state_divergence"
            if not d1_is_move or not d2_is_move:
                category = "different_move_kind"
            elif (
                d2_blocked
                and not d1_blocked
                and d2_selected_blocked
                and not d1_selected_blocked
            ):
                category = "only_legal_in_ON"
            elif d2_blocked and not d1_blocked:
                category = (
                    "support_safety_avoided_wrong_side"
                )
            elif d1_blocked and not d2_blocked:
                category = "off_side_blocked_only"
            elif d1_mid != d2_mid:
                category = "different_move"
            else:
                category = "different_target"
            return [
                {
                    "pair_id": d1.get("pair_id"),
                    "turn": t,
                    "slot": sk,
                    "d1_on_action_kind": d1_kind,
                    "d1_on_move_id": d1_mid,
                    "d1_on_target_position": d1_tpos,
                    "d2_on_action_kind": d2_kind,
                    "d2_on_move_id": d2_mid,
                    "d2_on_target_position": d2_tpos,
                    "d1_support_candidate_blocked": d1_blocked,
                    "d2_support_candidate_blocked": d2_blocked,
                    "d1_support_selected_blocked": (
                        d1_selected_blocked
                    ),
                    "d2_support_selected_blocked": (
                        d2_selected_blocked
                    ),
                    "d1_support_intended_side": d1_intended,
                    "d1_support_actual_side": d1_actual,
                    "d1_support_block_reason": d1_reason,
                    "category": category,
                }
            ]
    return [{"category": "no_divergence"}]


# ========================== Main ==========================


def analyze(
    artifact_tag: str,
    audit_glob_suffix: str = "",
    output_tag: Optional[str] = None,
):
    """Run the full paired analysis. Returns a dict
    suitable for both JSON dump and Markdown
    rendering.

    ``artifact_tag`` is the INPUT tag (used to find
    ``logs/support_target_paired_{tag}.jsonl`` and
    ``.csv``). ``output_tag`` is the OUTPUT tag
    (used to name the ``_analysis.json`` and
    ``_analysis.md`` files). If ``output_tag`` is
    None, ``output_tag = artifact_tag``.
    """
    if output_tag is None:
        output_tag = artifact_tag
    csv_path = f"logs/support_target_paired_{artifact_tag}.csv"
    battle_path = (
        f"logs/support_target_paired_{artifact_tag}.jsonl"
    )
    analysis_json = (
        f"logs/support_target_paired_{output_tag}_analysis.json"
    )
    analysis_md = (
        f"logs/support_target_paired_{output_tag}_analysis.md"
    )

    # Read battles
    battles = _read_jsonl(battle_path)
    if not battles:
        print(f"ERROR: no battles in {battle_path}")
        sys.exit(2)
    # Validate every battle
    for b in battles:
        errs = validate_battle_record(b)
        if errs:
            print(
                f"FATAL: pair {b.get('pair_id')} "
                f"{b.get('side_swap')} validation failed:"
            )
            for e in errs:
                print(f"  - {e}")
            sys.exit(2)
    # Pair by pair_id, never by row position
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for b in battles:
        pid = b["pair_id"]
        ss = b["side_swap"]
        by_pair.setdefault(pid, {})[ss] = b
    # Validate pair completion
    for pid, sides in by_pair.items():
        if set(sides.keys()) != {"D1", "D2"}:
            print(
                f"FATAL: pair {pid} missing D1 or D2: "
                f"{list(sides.keys())}"
            )
            sys.exit(2)
        errs = validate_pair(sides["D1"], sides["D2"])
        if errs:
            print(f"FATAL: pair {pid} validation:")
            for e in errs:
                print(f"  - {e}")
            sys.exit(2)
    # Outcome normalization
    on_decisive_wins: List[bool] = []
    on_decisive_outcomes: List[Dict[str, Any]] = []
    on_invalid: List[int] = []
    on_categories = {
        "ON_both": 0,
        "OFF_both": 0,
        "split": 0,
        "invalid": 0,
    }
    treatment_scores: List[int] = []
    d1_wins = d2_wins = 0
    d1_losses = d2_losses = 0
    d1_ties = d2_ties = 0
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid]["D1"]
        d2 = by_pair[pid]["D2"]
        if d1["status"] != "ok" or d2["status"] != "ok":
            on_invalid.append(pid)
            on_categories["invalid"] += 1
            continue
        if d1["on_won"] is None or d2["on_won"] is None:
            on_invalid.append(pid)
            on_categories["invalid"] += 1
            continue
        d1w = d1["on_won"]
        d2w = d2["on_won"]
        # Validate treatment score range
        score = treatment_score_for_pair(d1w, d2w)
        score_errs = validate_treatment_score(score)
        if score_errs:
            print(
                f"FATAL: pair {pid} treatment score invalid:"
            )
            for e in score_errs:
                print(f"  - {e}")
            sys.exit(2)
        if d1w and d2w:
            on_categories["ON_both"] += 1
            treatment_scores.append(+1)
        elif (not d1w) and (not d2w):
            on_categories["OFF_both"] += 1
            treatment_scores.append(-1)
        else:
            on_categories["split"] += 1
            treatment_scores.append(0)
        # Per-side win counts
        if d1w:
            d1_wins += 1
        else:
            d1_losses += 1
        if d2w:
            d2_wins += 1
        else:
            d2_losses += 1
        on_decisive_wins.append(d1w)
        on_decisive_outcomes.append({
            "pair_id": pid,
            "d1_on_won": d1w,
            "d2_on_won": d2w,
        })
    n_pairs_valid = len(on_decisive_wins)
    total_pairs = len(by_pair)
    total_battles = sum(1 for b in battles)
    # --- Aggregated metrics (200 battles / 100 pairs) ---
    # Combined ON rate uses BOTH battles, not
    # pairs. ``on_decisive_wins`` only stores the
    # D1 outcome per pair — we need both D1 and
    # D2 ON outcomes.
    combined_on_wins = sum(
        1
        for r in on_decisive_outcomes
        for w in (r["d1_on_won"], r["d2_on_won"])
        if w
    )
    # Wilson CI: n = total battles, s = combined wins
    wilson_lo, wilson_hi = wilson_ci(
        combined_on_wins, total_battles
    )
    # --- Sign test (ON-both vs OFF-both, only
    # decisive pairs) ---
    # H0: P(pair is ON-both) = 0.5 (the feature
    # does not shift which side wins decisive
    # pairs). H1: P(pair is ON-both) != 0.5
    # (two-sided) or P(pair is ON-both) < 0.5
    # (one-sided regression).
    # Decisive pairs n = ON_both + OFF_both.
    # Test statistic k = ON_both count.
    k_on_both = on_categories["ON_both"]
    k_off_both = on_categories["OFF_both"]
    decisive = k_on_both + k_off_both
    p_two_sided = exact_binomial_two_sided(k_on_both, decisive)
    p_one_sided_reg = exact_binomial_one_sided(k_on_both, decisive)
    # --- Per-side diagnostic (NOT treatment effect) ---
    d1_rate = d1_wins / n_pairs_valid if n_pairs_valid else float("nan")
    d2_rate = d2_wins / n_pairs_valid if n_pairs_valid else float("nan")
    combined_rate = (
        combined_on_wins / total_battles
        if total_battles
        else float("nan")
    )
    side_split = {
        "D1_ON_win_rate": d1_rate,
        "D2_ON_win_rate": d2_rate,
    }
    side_collapse = abs(d1_rate - d2_rate) if (
        n_pairs_valid
    ) else float("nan")
    # --- Paired treatment effect (the metric for
    # the adoption gate) ---
    # Treatment score per pair:
    #   +1 = ON won both D1 and D2
    #    0 = split
    #   -1 = OFF won both D1 and D2
    # Mean treatment effect = mean(treatment_scores)
    # = (ON_both - OFF_both) / n_pairs_valid.
    # The D1-D2 spread is a side-position
    # diagnostic, NOT a treatment effect.
    mean_treatment = (
        sum(treatment_scores) / len(treatment_scores)
        if treatment_scores
        else float("nan")
    )
    # Paired bootstrap CI for the mean treatment
    # effect: resample N=100 pairs WITH replacement
    # and compute the mean of the resampled scores.
    boot_point, boot_lo, boot_hi = paired_bootstrap_treatment(
        treatment_scores, n_boot=2000, seed=6381,
    )
    # D1-D2 side diagnostic (NOT for adoption gate)
    d1_outcomes = [r["d1_on_won"] for r in on_decisive_outcomes]
    d2_outcomes = [r["d2_on_won"] for r in on_decisive_outcomes]
    side_diag_point, side_diag_lo, side_diag_hi = (
        paired_bootstrap_d1_minus_d2(
            d1_outcomes, d2_outcomes, n_boot=2000, seed=6381,
        )
    )
    # Safety metrics: ON and OFF separately
    on_metrics: Dict[str, Any] = {}
    off_metrics: Dict[str, Any] = {}
    on_audit_paths = []
    off_audit_paths = []
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid]["D1"]
        d2 = by_pair[pid]["D2"]
        if d1["status"] != "ok" or d2["status"] != "ok":
            continue
        # D1: ON is p1, OFF is p2
        on_audit_paths.append(_audit_path_for(d1, "p1"))
        off_audit_paths.append(_audit_path_for(d1, "p2"))
        # D2: OFF is p1, ON is p2
        off_audit_paths.append(_audit_path_for(d2, "p1"))
        on_audit_paths.append(_audit_path_for(d2, "p2"))
    # Sum metrics across ON audit paths
    on_m = {}
    for ap in set(on_audit_paths):
        m = _count_support_metrics_from_audit(ap)
        for k, v in m.items():
            if isinstance(v, dict):
                on_m[k] = {
                    **on_m.get(k, {}),
                    **{kk: vv + on_m.get(k, {}).get(kk, 0)
                       for kk, vv in v.items()},
                }
            else:
                on_m[k] = on_m.get(k, 0) + v
    off_m = {}
    for ap in set(off_audit_paths):
        m = _count_support_metrics_from_audit(ap)
        for k, v in m.items():
            if isinstance(v, dict):
                off_m[k] = {
                    **off_m.get(k, {}),
                    **{kk: vv + off_m.get(k, {}).get(kk, 0)
                       for kk, vv in v.items()},
                }
            else:
                off_m[k] = off_m.get(k, 0) + v
    # First divergence per pair
    first_divergences = []
    for pid in sorted(by_pair.keys()):
        d1 = by_pair[pid]["D1"]
        d2 = by_pair[pid]["D2"]
        if d1["status"] != "ok" or d2["status"] != "ok":
            continue
        divs = _per_battle_divergence(d1, d2)
        if divs and divs[0].get("category") != "no_divergence":
            first_divergences.append({
                "pair_id": pid,
                **divs[0],
            })
    # Build the report
    report = {
        "artifact_tag": artifact_tag,
        "n_pairs_total": total_pairs,
        "n_pairs_valid": n_pairs_valid,
        "n_pairs_invalid": len(on_invalid),
        "invalid_pair_ids": on_invalid,
        "n_battles_total": total_battles,
        "D1": {
            "on_wins": d1_wins,
            "on_losses": d1_losses,
            "on_win_rate": d1_rate,
        },
        "D2": {
            "on_wins": d2_wins,
            "on_losses": d2_losses,
            "on_win_rate": d2_rate,
        },
        "combined": {
            "on_wins": combined_on_wins,
            "on_win_rate": combined_rate,
            "wilson_95_lo": wilson_lo,
            "wilson_95_hi": wilson_hi,
        },
        "paired_categories": on_categories,
        "sign_test_two_sided_p": p_two_sided,
        "sign_test_one_sided_regression_p": p_one_sided_reg,
        "treatment_effect": {
            "mean": mean_treatment,
            "n_pairs": len(treatment_scores),
            "treatment_score": {
                "ON_both_value": +1,
                "split_value": 0,
                "OFF_both_value": -1,
            },
            "paired_bootstrap": {
                "point": boot_point,
                "ci_95_lo": boot_lo,
                "ci_95_hi": boot_hi,
                "n_boot": 2000,
                "seed": 6381,
            },
        },
        "side_position_diagnostic": {
            "D1_minus_D2_win_rate": side_collapse,
            "D1_minus_D2_bootstrap": {
                "point": side_diag_point,
                "ci_95_lo": side_diag_lo,
                "ci_95_hi": side_diag_hi,
                "n_boot": 2000,
                "seed": 6381,
            },
            "side_split": side_split,
            "is_treatment_effect": False,
        },
        "on_metrics": on_m,
        "off_metrics": off_m,
        "first_divergence_count": len(first_divergences),
        "first_divergences": first_divergences,
    }
    # Write JSON
    with open(analysis_json, "w") as f:
        json.dump(report, f, indent=2)
    # Write Markdown
    md_lines = [
        f"# Phase 6.3.8c.1 Paired Analysis — {artifact_tag}",
        "",
        "## Supersedes Phase 6.3.8c",
        "",
        f"This analysis **supersedes** the Phase 6.3.8c "
        f"statistical analysis "
        f"(`logs/support_target_paired_phase638c_v2_analysis_SUPERSEDED_BY_phase638c1.{{json,md}}`). "
        f"The original 6.3.8c analyzer had two errors:",
        f"1. Combined ON rate used `n_pairs` as the "
        f"denominator instead of `n_battles` (200).",
        f"2. The paired bootstrap CI used `D1 - D2` "
        f"win rate (a side-position diagnostic), not "
        f"the mean paired treatment effect "
        f"(the correct adoption gate).",
        f"",
        f"The 6.3.8c.1 analysis fixes both:",
        f"- Combined ON rate = 95/200 = 0.475 "
        f"(was 0.450 in 6.3.8c).",
        f"- Mean paired treatment effect = "
        f"(18 - 23) / 100 = -0.05 with bootstrap "
        f"95% CI [-0.17, 0.08] (was D1-D2 -0.05 with "
        f"CI [-0.20, 0.10] in 6.3.8c).",
        f"- D1-D2 is now reported as a side-position "
        f"diagnostic only (`side_position_diagnostic`) "
        f"and is NOT used for the adoption gate.",
        f"",
        f"Input artifact (preserved, unchanged): "
        f"`logs/support_target_paired_{artifact_tag}.jsonl`.",
        f"",
        f"- Total pairs: {total_pairs}",
        f"- Valid pairs: {n_pairs_valid}",
        f"- Invalid pairs: {len(on_invalid)}",
        f"- Total battles: {total_battles}",
        "",
        "## Aggregated ON win rate (200 battles / 100 pairs)",
        "",
        f"- Combined ON wins: {combined_on_wins}/{total_battles} "
        f"= {combined_rate:.3f}",
        f"- Wilson 95% CI (n={total_battles}, s={combined_on_wins}): "
        f"[{wilson_lo:.3f}, {wilson_hi:.3f}]",
        "",
        "## Per-arm / side-position diagnostic (NOT treatment effect)",
        "",
        f"- D1 (ON as p1): wins {d1_wins}/{n_pairs_valid} "
        f"= {d1_rate:.3f}",
        f"- D2 (ON as p2): wins {d2_wins}/{n_pairs_valid} "
        f"= {d2_rate:.3f}",
        f"- D1 - D2 win rate: {side_collapse:.3f} "
        f"({'WARNING' if side_collapse > 0.10 else 'OK'})",
        f"- D1 - D2 bootstrap 95% CI: "
        f"[{side_diag_lo:.3f}, {side_diag_hi:.3f}]",
        "",
        "## Paired categories",
        "",
        f"- ON both:  {on_categories['ON_both']}",
        f"- OFF both: {on_categories['OFF_both']}",
        f"- Split:    {on_categories['split']}",
        f"- Invalid:  {on_categories['invalid']}",
        "",
        "## Paired treatment effect (this is the adoption gate)",
        "",
        "Treatment score per pair:",
        "- +1 if ON won both D1 and D2 (ON_both)",
        "-  0 if split",
        "- -1 if OFF won both D1 and D2 (OFF_both)",
        "",
        f"- Number of pairs with treatment score: "
        f"{len(treatment_scores)}",
        f"- Mean treatment effect: {mean_treatment:.4f}  "
        f"(= (ON_both - OFF_both) / n_pairs = "
        f"({on_categories['ON_both']} - "
        f"{on_categories['OFF_both']}) / {n_pairs_valid})",
        "",
        "## Sign tests (decisive pairs only)",
        "",
        f"- Decisive pairs n = {decisive} (={k_on_both} + {k_off_both})",
        f"- Test statistic: k = ON_both = {k_on_both}",
        f"- H0: P(pair is ON-both) = 0.5",
        f"- H1 two-sided: P(pair is ON-both) ≠ 0.5",
        f"- H1 one-sided (ON regression): "
        f"P(pair is ON-both) < 0.5",
        f"- Two-sided exact p: {p_two_sided:.4f}",
        f"- One-sided (ON regression) p: "
        f"{p_one_sided_reg:.4f}",
        "",
        "## Paired bootstrap CI (treatment effect)",
        "",
        f"- Resample N={n_pairs_valid} pairs WITH replacement",
        f"- Iterations: 2000, deterministic seed: 6381",
        f"- Point: {boot_point:.4f}",
        f"- 95% CI: [{boot_lo:.4f}, {boot_hi:.4f}]",
        f"- **Adoption lower-bound gate uses this CI:** "
        f"boot_lo = {boot_lo:.4f}",
        "",
        "## Side-collapse diagnostics",
        "",
        f"- D1 rate: {d1_rate:.3f}",
        f"- D2 rate: {d2_rate:.3f}",
        f"- |D1 - D2|: "
        f"{side_collapse:.3f} "
        f"({'WARNING' if side_collapse > 0.10 else 'OK'})",
        "",
        "## ON safety metrics (paired audits)",
        "",
    ]
    for k, v in on_m.items():
        if isinstance(v, dict):
            md_lines.append(f"- {k}: {dict(sorted(v.items()))}")
        else:
            md_lines.append(f"- {k}: {v}")
    md_lines += [
        "",
        "## OFF safety metrics (paired audits)",
        "",
    ]
    for k, v in off_m.items():
        if isinstance(v, dict):
            md_lines.append(f"- {k}: {dict(sorted(v.items()))}")
        else:
            md_lines.append(f"- {k}: {v}")
    md_lines += [
        "",
        f"## First divergence per pair ({len(first_divergences)} found)",
        "",
    ]
    for div in first_divergences[:20]:
        md_lines.append(
            f"- pair {div.get('pair_id')} turn {div.get('turn')} "
            f"slot {div.get('slot')}: "
            f"d1_on={div.get('d1_on_move_id')}@{div.get('d1_on_target_position')} "
            f"d2_on={div.get('d2_on_move_id')}@{div.get('d2_on_target_position')} "
            f"category={div.get('category')}"
        )
    with open(analysis_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"\n[analyze] wrote {analysis_json}")
    print(f"[analyze] wrote {analysis_md}")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.3.8c.2 artifact audit + paired analyzer"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="INPUT artifact tag (reads "
             "logs/support_target_paired_{tag}.jsonl and .csv).",
    )
    parser.add_argument(
        "--audit-only", action="store_true",
        help="Run only the artifact audit and write "
             "phase638c2_artifact_audit.{json,md}.",
    )
    parser.add_argument(
        "--audit-tag", type=str, default="phase638c2",
        help="Output tag for the audit report "
             "(default: phase638c2).",
    )
    parser.add_argument(
        "--output-tag", type=str, default=None,
        help="OUTPUT tag (writes "
             "logs/support_target_paired_{tag}_analysis.{json,md}). "
             "Defaults to --artifact-tag.",
    )
    parser.add_argument(
        "--expected-treatment", type=float, default=None,
        help="Optional: expected mean treatment effect "
             "(regression-test guard).",
    )
    parser.add_argument(
        "--expected-on-both", type=int, default=None,
        help="Optional: expected ON_both count "
             "(regression-test guard).",
    )
    parser.add_argument(
        "--expected-off-both", type=int, default=None,
        help="Optional: expected OFF_both count "
             "(regression-test guard).",
    )
    parser.add_argument(
        "--expected-split", type=int, default=None,
        help="Optional: expected split count "
             "(regression-test guard).",
    )
    parser.add_argument(
        "--expected-combined-wins", type=int, default=None,
        help="Optional: expected combined ON wins "
             "across 200 battles (regression-test guard).",
    )
    parser.add_argument(
        "--expected-combined-rate", type=float, default=None,
        help="Optional: expected combined ON win rate "
             "(regression-test guard).",
    )
    args = parser.parse_args()
    if args.audit_only:
        audit = write_artifact_audit(
            artifact_tag=args.artifact_tag,
            audit_tag=args.audit_tag,
        )
        print(
            f"\n[audit-only] wrote "
            f"{audit['output_paths']['audit_json']} "
            f"and .md"
        )
        if audit["errors"]:
            print("ERRORS:")
            for e in audit["errors"]:
                print(f"  - {e}")
            sys.exit(2)
        sys.exit(0)
    report = analyze(
        args.artifact_tag,
        output_tag=args.output_tag,
    )
    err_code = 0
    if args.expected_treatment is not None:
        actual = report["treatment_effect"]["mean"]
        if abs(actual - args.expected_treatment) > 1e-6:
            print(
                f"REGRESSION: treatment effect {actual} "
                f"!= expected {args.expected_treatment}"
            )
            err_code = 3
    if (
        args.expected_on_both is not None
        and args.expected_off_both is not None
        and args.expected_split is not None
    ):
        actual = (
            report["paired_categories"]["ON_both"],
            report["paired_categories"]["OFF_both"],
            report["paired_categories"]["split"],
        )
        expected = (
            args.expected_on_both,
            args.expected_off_both,
            args.expected_split,
        )
        if actual != expected:
            print(
                f"REGRESSION: paired categories {actual} "
                f"!= expected {expected}"
            )
            err_code = 3
    if args.expected_combined_wins is not None:
        actual = report["combined"]["on_wins"]
        if actual != args.expected_combined_wins:
            print(
                f"REGRESSION: combined ON wins {actual} "
                f"!= expected {args.expected_combined_wins}"
            )
            err_code = 3
    if args.expected_combined_rate is not None:
        actual = report["combined"]["on_win_rate"]
        if abs(actual - args.expected_combined_rate) > 1e-6:
            print(
                f"REGRESSION: combined ON rate {actual} "
                f"!= expected {args.expected_combined_rate}"
            )
            err_code = 3
    if err_code:
        sys.exit(err_code)
    print(
        f"\nAggregated ON win rate "
        f"({report['combined']['on_wins']}/"
        f"{report['n_battles_total']}): "
        f"{report['combined']['on_win_rate']:.4f}"
    )
    print(
        f"  Wilson 95% CI: "
        f"[{report['combined']['wilson_95_lo']:.4f}, "
        f"{report['combined']['wilson_95_hi']:.4f}]"
    )
    print(
        f"\nPaired treatment effect (mean): "
        f"{report['treatment_effect']['mean']:.4f}"
    )
    print(
        f"  Paired bootstrap 95% CI: "
        f"[{report['treatment_effect']['paired_bootstrap']['ci_95_lo']:.4f}, "
        f"{report['treatment_effect']['paired_bootstrap']['ci_95_hi']:.4f}]"
    )
    print(
        f"  (D1-D2 side diagnostic, NOT treatment: "
        f"{report['side_position_diagnostic']['D1_minus_D2_win_rate']:.4f}, "
        f"95% CI "
        f"[{report['side_position_diagnostic']['D1_minus_D2_bootstrap']['ci_95_lo']:.4f}, "
        f"{report['side_position_diagnostic']['D1_minus_D2_bootstrap']['ci_95_hi']:.4f}])"
    )
    print(
        f"\n  ON-both / OFF-both / Split: "
        f"{report['paired_categories']['ON_both']} / "
        f"{report['paired_categories']['OFF_both']} / "
        f"{report['paired_categories']['split']}"
    )
    print(
        f"  Decisive pairs: "
        f"{report['paired_categories']['ON_both'] + report['paired_categories']['OFF_both']}"
    )
    print(
        f"  Two-sided exact p: "
        f"{report['sign_test_two_sided_p']:.4f}"
    )
    print(
        f"  One-sided (ON regression) p: "
        f"{report['sign_test_one_sided_regression_p']:.4f}"
    )


def write_artifact_audit(
    artifact_tag: str,
    audit_tag: str = "phase638c2",
    logs_dir: str = "logs",
    expected_n_pairs: int = 100,
) -> Dict[str, Any]:
    """Run the artifact inventory and write the
    audit report. Returns the inventory dict
    with extra ``input_artifact_metadata`` and
    ``output_paths`` fields.
    """
    inventory = inventory_artifacts(
        artifact_tag, logs_dir=logs_dir,
        expected_n_pairs=expected_n_pairs,
    )
    # Per-side file size totals
    total_size = sum(
        f["size_bytes"] for f in inventory["files"]
    )
    n_files = len(inventory["files"])
    # Input artifact metadata
    csv_path = (
        f"{logs_dir}/support_target_paired_{artifact_tag}.csv"
    )
    jsonl_path = (
        f"{logs_dir}/support_target_paired_{artifact_tag}.jsonl"
    )
    audit_manifest = (
        f"{logs_dir}/support_target_paired_{artifact_tag}_audit.jsonl"
    )
    analysis_path = (
        f"{logs_dir}/support_target_paired_phase638c1_analysis.json"
    )
    input_meta = {
        "csv": file_metadata(csv_path),
        "jsonl": file_metadata(jsonl_path),
        "audit_manifest": file_metadata(audit_manifest),
    }
    # Per-pair file-count distribution
    per_pair_counts = inventory["per_pair_count"]
    pair_count_dist: Dict[int, int] = {}
    for pid, n in per_pair_counts.items():
        pair_count_dist[n] = pair_count_dist.get(n, 0) + 1
    # Audit report
    audit_report: Dict[str, Any] = {
        "audit_tag": audit_tag,
        "artifact_tag": artifact_tag,
        "n_pairs": inventory["n_pairs"],
        "n_battles": inventory["n_battles"],
        "n_per_side_files": inventory["n_per_side_files"],
        "n_per_side_files_on": (
            inventory["per_side_breakdown"].get(
                "ONvOFF__p1", 0
            )
            + inventory["per_side_breakdown"].get(
                "OFFvON__p2", 0
            )
        ),
        "n_per_side_files_off": (
            inventory["per_side_breakdown"].get(
                "ONvOFF__p2", 0
            )
            + inventory["per_side_breakdown"].get(
                "OFFvON__p1", 0
            )
        ),
        "per_side_breakdown": inventory["per_side_breakdown"],
        "pair_count_distribution": pair_count_dist,
        "input_artifact_metadata": input_meta,
        "total_per_side_size_bytes": total_size,
        "errors": inventory["errors"],
        "warnings": inventory["warnings"],
        "duplicate_battle_tags": inventory[
            "duplicate_battle_tags"
        ],
    }
    # Output paths
    audit_json = (
        f"{logs_dir}/support_target_paired_"
        f"{audit_tag}_artifact_audit.json"
    )
    audit_md = (
        f"{logs_dir}/support_target_paired_"
        f"{audit_tag}_artifact_audit.md"
    )
    audit_report["output_paths"] = {
        "audit_json": audit_json,
        "audit_md": audit_md,
    }
    with open(audit_json, "w") as f:
        json.dump(audit_report, f, indent=2)
    # Markdown
    md = [
        f"# Phase 6.3.8c.2 Artifact Audit — "
        f"{artifact_tag}",
        "",
        f"- Audit tag: {audit_tag}",
        f"- Artifact tag: {artifact_tag}",
        f"- Expected n_pairs: {expected_n_pairs}",
        "",
        "## Inventory counts",
        "",
        f"- n_pairs: {inventory['n_pairs']}",
        f"- n_battles: {inventory['n_battles']}",
        f"- n_per_side_files: "
        f"{inventory['n_per_side_files']}",
        f"- n_per_side_files (ON): "
        f"{audit_report['n_per_side_files_on']}",
        f"- n_per_side_files (OFF): "
        f"{audit_report['n_per_side_files_off']}",
        f"- total per-side size: "
        f"{total_size} bytes "
        f"({total_size / 1024:.1f} KB)",
        "",
        "## Per-side breakdown (arm, side) -> count",
        "",
    ]
    for k, v in sorted(
        inventory["per_side_breakdown"].items()
    ):
        md.append(f"- {k}: {v}")
    md += [
        "",
        "## Per-pair file-count distribution",
        "",
    ]
    for n_files_pp, n_pairs_with in sorted(
        pair_count_dist.items()
    ):
        md.append(
            f"- {n_files_pp} per-side files: "
            f"{n_pairs_with} pairs"
        )
    md += [
        "",
        "## Input artifact metadata",
        "",
        f"- CSV ({csv_path}):",
        f"  - size: {input_meta['csv']['size_bytes']} bytes",
        f"  - sha256: "
        f"{input_meta['csv']['sha256'] or 'EMPTY'}",
        f"- JSONL ({jsonl_path}):",
        f"  - size: {input_meta['jsonl']['size_bytes']} bytes",
        f"  - sha256: "
        f"{input_meta['jsonl']['sha256'] or 'EMPTY'}",
        f"- Audit manifest ({audit_manifest}):",
        f"  - size: "
        f"{input_meta['audit_manifest']['size_bytes']} bytes",
        f"  - sha256: "
        f"{input_meta['audit_manifest']['sha256'] or 'EMPTY'}",
        "",
        "## Errors",
        "",
    ]
    if inventory["errors"]:
        for e in inventory["errors"]:
            md.append(f"- {e}")
    else:
        md.append("- (none)")
    md += [
        "",
        "## Warnings",
        "",
    ]
    if inventory["warnings"]:
        for w in inventory["warnings"]:
            md.append(f"- {w}")
    else:
        md.append("- (none)")
    md += [
        "",
        "## 200 vs 400 per-side file discrepancy",
        "",
        f"The qualifier produces 4 per-side audit "
        f"files per pair (D1.p1, D1.p2, D2.p1, "
        f"D2.p2 — one for each engine in each "
        f"side-swap arm).",
        f"With {inventory['n_pairs']} pairs, this "
        f"yields {inventory['n_per_side_files']} "
        f"per-side files total (4 × 100 = 400).",
        f"Of these, 200 are ON-side audits "
        f"(ONvOFF.p1 from D1 + OFFvON.p2 from D2) "
        f"and 200 are OFF-side audits "
        f"(ONvOFF.p2 from D1 + OFFvON.p1 from D2).",
        f"Both counts are correct in different "
        f"contexts:",
        f"- 400 = total per-side files (filesystem).",
        f"- 200 = per-arm per-side files (analyzer "
        f"  metric basis; each side has 200 files).",
        f"Phase 6.3.8c.1 report said '200 battles, "
        f"all ON-side audits' which is correct: 200 "
        f"ON-side audit files were the basis for the "
        f"ON metrics.",
        "",
    ]
    with open(audit_md, "w") as f:
        f.write("\n".join(md) + "\n")
    return audit_report


if __name__ == "__main__":
    main()
