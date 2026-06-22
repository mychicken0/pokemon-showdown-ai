#!/usr/bin/env python3
"""Phase V3c.2 — 20-pair VGC reality check
learned_preview_v3c1 vs matchup_top4_v3.

Ponytail: small focused module. Reuses the V3a.2
runner's ControlledTeamPreviewPlayer and
build_team_string. Implements a single
run_v3c2_battle helper that mirrors the V3a.2
runner with:
  - V3c2_ account prefix (visible in browser)
  - player_policy="learned_preview_v3c1" for the
    learned arm
  - battle_format="gen9championsvgc2026regma"
  - FileNotFoundError if V3c.1 model is missing
    (preflight)

Hard rules:
- 20 pairs × 2 sides = 40 battles.
- Localhost only.
- No training, no model changes, no policy
  wrapper changes, no default changes.
- Overwrite guarded by --overwrite.
"""
import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from poke_env import AccountConfiguration  # noqa: E402

from bot_vgc2026_phaseV2c import (  # noqa: E402
    ControlledTeamPreviewPlayer,
    build_team_string,
    validate_team_for_battle,
)
from bot_vgc2026_phaseV3a2_reality import (  # noqa: E402
    BATTLE_FORMAT,
    check_localhost,
    init_artifacts,
)
from vgc_team_pool import load_vgc_pool  # noqa: E402


ACCOUNT_PREFIX_V3C2 = "V3c2_"
DEFAULT_TAG = "phaseV3c2_learned_v3c1_vs_v3_reality20"
LOG_DIR = "logs"
POLICY_LEARNED = "learned_preview_v3c1"
POLICY_BASELINE = "matchup_top4_v3"
LEARNED_POLICY_SET = frozenset({
    "learned_preview_v3a1", "learned_preview_v3c1",
    "learned_preview_v3a",
})


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def preflight() -> Optional[str]:
    """Return None on success or an error string.
    ponytail: explicit failure surface so the
    runner can refuse to start cleanly.
    """
    if not check_localhost():
        return "localhost:8000 not healthy"
    model_path = "logs/vgc2026_phaseV3c1_model.json"
    if not os.path.isfile(model_path):
        return f"V3c.1 model missing at {model_path}"
    from team_preview_policy import choose_four_from_six
    import inspect
    if inspect.signature(
        choose_four_from_six
    ).parameters["policy"].default != "basic_top4":
        return "default policy changed (expected basic_top4)"
    # Smoke test: try the V3c.1 wrapper.
    team = [
        {"species": s, "moves": ["Tackle"], "ability": ""}
        for s in ["a", "b", "c", "d", "e", "f"]
    ]
    try:
        result = choose_four_from_six(
            team, team, policy=POLICY_LEARNED
        )
    except Exception as e:
        return f"learned_preview_v3c1 wrapper failed: {e}"
    if not result.chosen_4 or len(result.chosen_4) != 4:
        return "learned_preview_v3c1 returned invalid plan"
    return None


# ---------------------------------------------------------------------------
# Per-battle runner (V3c.2 variant)
# ---------------------------------------------------------------------------


def _make_v3c2_name(pair_id: int, side: str, learned: bool) -> str:
    """Visible account name: V3c2_p<pair>_<side>L|V.
    ponytail: same shape as V3a.2 with V3c2_
    prefix. Truncated to 18 chars like V3a.2.
    """
    suffix = "L" if learned else "V"
    return f"{ACCOUNT_PREFIX_V3C2}p{pair_id:02d}_{side}{suffix}"[:18]


async def run_v3c2_battle(
    pair_id: int,
    side: str,
    player_policy: str,
    opponent_policy: str,
    our_team_idx: int,
    opp_team_idx: int,
    pool: Any,
    seed: int = 42,
    timeout: float = 90.0,
) -> Dict[str, Any]:
    """Run one VGC battle using the V3a.2
    ControlledTeamPreviewPlayer with V3c2_ prefix
    and player_policy being either
    learned_preview_v3c1 or matchup_top4_v3.
    """
    from bot_vgc2026_phaseV3a2_reality import pick_preview

    our_team_row = pool.get_team(our_team_idx)
    opp_team_row = pool.get_team(opp_team_idx)
    if our_team_row is None or opp_team_row is None:
        return {
            "pair_id": pair_id, "side": side,
            "our_policy": player_policy,
            "opponent_policy": opponent_policy,
            "status": "no_team", "our_win": None, "turns": 0,
            "error_detail": (
                f"team lookup failed: "
                f"our={our_team_idx} opp={opp_team_idx}"
            ),
        }
    our_team = our_team_row.pokemon
    opp_team = opp_team_row.pokemon
    our_preview = pick_preview(
        our_team, player_policy,
        opponent_team=opp_team, seed=seed,
    )
    opp_preview = pick_preview(
        opp_team, opponent_policy,
        opponent_team=our_team, seed=seed + 1,
    )
    our_team_str = build_team_string(
        our_team, our_preview.chosen_4
    )
    opp_team_str = build_team_string(
        opp_team, opp_preview.chosen_4
    )
    valid, err = validate_team_for_battle(our_team_str)
    if not valid:
        return {
            "pair_id": pair_id, "side": side,
            "our_policy": player_policy,
            "opponent_policy": opponent_policy,
            "status": "team_serialization",
            "our_win": None, "turns": 0,
            "error_detail": f"our team: {err}",
        }
    valid, err = validate_team_for_battle(opp_team_str)
    if not valid:
        return {
            "pair_id": pair_id, "side": side,
            "our_policy": player_policy,
            "opponent_policy": opponent_policy,
            "status": "team_serialization",
            "our_win": None, "turns": 0,
            "error_detail": f"opp team: {err}",
        }
    # Player names. ponytail: learned-or-not based
    # on whether our_policy is in the learned set.
    is_learned_first = (
        side == "p1" and player_policy in LEARNED_POLICY_SET
    )
    is_learned_second = (
        side == "p2" and player_policy in LEARNED_POLICY_SET
    )
    p1_name = _make_v3c2_name(pair_id, "p1", is_learned_first)
    p2_name = _make_v3c2_name(pair_id, "p2", is_learned_second)
    p1 = ControlledTeamPreviewPlayer(
        account_configuration=AccountConfiguration(p1_name, None),
        preview_result=our_preview if side == "p1" else opp_preview,
        battle_tag=f"battle-gen9championsvgc2026regma-{pair_id:03d}-{side}",
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        log_level=30,
        team=our_team_str if side == "p1" else opp_team_str,
    )
    p2 = ControlledTeamPreviewPlayer(
        account_configuration=AccountConfiguration(p2_name, None),
        preview_result=opp_preview if side == "p1" else our_preview,
        battle_tag=f"battle-gen9championsvgc2026regma-{pair_id:03d}-{side}",
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        log_level=30,
        team=opp_team_str if side == "p1" else our_team_str,
    )
    if side == "p2":
        p1.preview_result = opp_preview
        p2.preview_result = our_preview
    started = datetime.utcnow().isoformat()
    battle_tag = f"battle-gen9championsvgc2026regma-{pair_id:03d}-{side}"
    status = "ok"
    error_detail = ""
    our_win: Optional[bool] = None
    turns = 0
    try:
        await asyncio.wait_for(
            p1.battle_against(p2, n_battles=1),
            timeout=timeout,
        )
        finished = p1.n_finished_battles
        p1_wins = p1.n_won_battles
        p2_wins = p2.n_won_battles
        if finished == 0:
            status = "no_battle"
        else:
            if side == "p1":
                our_win = bool(p1_wins and not p2_wins)
            else:
                our_win = bool(p2_wins and not p1_wins)
            try:
                battle = next(iter(p1.battles.values()))
                turns = len(battle.turns)
            except Exception:
                turns = 0
    except asyncio.TimeoutError:
        status = "timeout"
        error_detail = f"timeout after {timeout}s"
    except Exception as e:
        status = "error"
        error_detail = str(e)
    finally:
        try:
            await p1.stop_auto_battling()
        except Exception:
            pass
        try:
            await p2.stop_auto_battling()
        except Exception:
            pass
    finished = datetime.utcnow().isoformat()
    return {
        "pair_id": pair_id,
        "side": side,
        "team_id": f"team_{our_team_idx}",
        "opponent_team_id": f"team_{opp_team_idx}",
        "player_policy": player_policy,
        "opponent_policy": opponent_policy,
        "battle_tag": battle_tag,
        "started_at": started,
        "finished_at": finished,
        "status": status,
        "our_win": our_win,
        "turns": turns,
        "error_detail": error_detail,
        "our_chosen_4": list(our_preview.chosen_4),
        "our_lead_2": list(our_preview.lead_2),
        "our_back_2": list(our_preview.back_2),
        "opp_chosen_4": list(opp_preview.chosen_4),
        "opp_lead_2": list(opp_preview.lead_2),
        "opp_back_2": list(opp_preview.back_2),
    }


# ---------------------------------------------------------------------------
# 20-pair run
# ---------------------------------------------------------------------------


def run_v3c2_reality(
    n_pairs: int = 20,
    start_pair: int = 0,
    seed: int = 42,
    timeout: float = 90.0,
    overwrite: bool = False,
    tag: str = DEFAULT_TAG,
) -> Dict[str, Any]:
    """Run n_pairs of side-swapped VGC battles:
    D1: learned as p1, V3 as p2.
    D2: V3 as p1, learned as p2.
    Total: 2 * n_pairs battles.
    """
    err = preflight()
    if err is not None:
        return {"error": err}
    csv_path, jsonl_path, _ = init_artifacts(tag, overwrite)
    pool = load_vgc_pool()
    start_time = time.time()
    results: List[Dict[str, Any]] = []
    for pair_id in range(start_pair, start_pair + n_pairs):
        our_idx = pair_id % len(pool)
        opp_idx = pair_id % len(pool)
        d1 = asyncio.run(
            run_v3c2_battle(
                pair_id, "p1", POLICY_LEARNED, POLICY_BASELINE,
                our_idx, opp_idx, pool, seed=seed,
                timeout=timeout,
            )
        )
        d2 = asyncio.run(
            run_v3c2_battle(
                pair_id, "p2", POLICY_BASELINE, POLICY_LEARNED,
                our_idx, opp_idx, pool, seed=seed,
                timeout=timeout,
            )
        )
        results.extend([d1, d2])
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            for r in (d1, d2):
                writer.writerow([
                    r["pair_id"], r["side"], r["our_policy"],
                    r["opponent_policy"], r["battle_tag"],
                    r["started_at"], r["finished_at"],
                    r["status"], r["our_win"], r["turns"],
                    r["error_detail"],
                    "|".join(r["our_chosen_4"]),
                    "|".join(r["our_lead_2"]),
                    "|".join(r["our_back_2"]),
                    "|".join(r["opp_chosen_4"]),
                    "|".join(r["opp_lead_2"]),
                    "|".join(r["opp_back_2"]),
                ])
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(d1) + "\n")
            f.write(json.dumps(d2) + "\n")
        elapsed = time.time() - start_time
        print(
            f"  pair {pair_id:03d} done ({elapsed:.0f}s) "
            f"| D1 {d1['status']}/{d1['our_win']} "
            f"| D2 {d2['status']}/{d2['our_win']}",
            flush=True,
        )
    return {
        "tag": tag,
        "csv_path": str(csv_path),
        "jsonl_path": str(jsonl_path),
        "n_pairs": n_pairs,
        "n_battles": len(results),
        "elapsed_s": time.time() - start_time,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Validation + gates
# ---------------------------------------------------------------------------


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _validate_v3c2(
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Per-battle validation. ponytail: reuses
    V3a.2 validation patterns.
    """
    n_battles = len(rows)
    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_bad_status = n_battles - n_ok
    n_chosen_4_ok = sum(
        1 for r in rows
        if len(r.get("our_chosen_4", [])) == 4
    )
    n_lead_2_ok = sum(
        1 for r in rows
        if len(r.get("our_lead_2", [])) == 2
    )
    n_back_2_ok = sum(
        1 for r in rows
        if len(r.get("our_back_2", [])) == 2
    )
    pair_ids = {r.get("pair_id") for r in rows}
    sides = {(r.get("pair_id"), r.get("side")) for r in rows}
    n_complete_pairs = sum(
        1 for p in pair_ids
        if (p, "p1") in sides and (p, "p2") in sides
    )
    battle_tags = [r.get("battle_tag", "") for r in rows]
    dup_tags = sum(
        1 for t, n in Counter(battle_tags).items() if n > 1
    )
    return {
        "n_battles": n_battles,
        "n_ok": n_ok,
        "n_bad_status": n_bad_status,
        "n_chosen_4_ok": n_chosen_4_ok,
        "n_lead_2_ok": n_lead_2_ok,
        "n_back_2_ok": n_back_2_ok,
        "n_unique_pairs": len(pair_ids),
        "n_complete_pairs": n_complete_pairs,
        "n_duplicate_tags": dup_tags,
    }


def _win_counts_by_side(
    rows: List[Dict[str, Any]],
) -> Tuple[int, int, int, int]:
    """Return (learned_p1, learned_p2, v3_p1, v3_p2).
    ponytail: learned won as p1 means our_policy is
    learned and our_win=True.
    """
    learned_p1 = 0
    learned_p2 = 0
    v3_p1 = 0
    v3_p2 = 0
    for r in rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_win") is None:
            continue
        is_learned = r.get("our_policy") == POLICY_LEARNED
        if r.get("our_win"):
            if is_learned and r.get("side") == "p1":
                learned_p1 += 1
            if is_learned and r.get("side") == "p2":
                learned_p2 += 1
            if (not is_learned) and r.get("side") == "p1":
                v3_p1 += 1
            if (not is_learned) and r.get("side") == "p2":
                v3_p2 += 1
    return learned_p1, learned_p2, v3_p1, v3_p2


def _paired_categories(
    rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Decisive per (pair_id, side) group. ponytail:
    learned_both = learned won both D1 and D2.
    v3_both = V3 won both. split = mixed.
    Layout: D1 has learned as p1; D2 has V3 as p1.
    learned won D1 if D1.our_win=True. learned won
    D2 if D2.our_win=False (learned is opp in D2).
    """
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_win") is None:
            continue
        p = r.get("pair_id")
        s = r.get("side")
        by_pair.setdefault(p, {})[s] = r
    learned_both = 0
    v3_both = 0
    split = 0
    invalid = 0
    for p, sides in by_pair.items():
        if "p1" not in sides or "p2" not in sides:
            invalid += 1
            continue
        d1, d2 = sides["p1"], sides["p2"]
        learned_d1 = bool(d1["our_win"])
        learned_d2 = not bool(d2["our_win"])
        if learned_d1 and learned_d2:
            learned_both += 1
        elif (not learned_d1) and (not learned_d2):
            v3_both += 1
        else:
            split += 1
    return {
        "learned_both": learned_both,
        "v3_both": v3_both,
        "split": split,
        "invalid": invalid,
    }


def _wilson_ci(
    wins: int, total: int, z: float = 1.96
) -> Tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = wins / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    half = z * (
        (p * (1 - p) / total + z * z / (4 * total * total))
        ** 0.5
    )
    return (
        max(0.0, (centre - half) / denom),
        min(1.0, (centre + half) / denom),
    )


def _paired_bootstrap(
    rows: List[Dict[str, Any]],
    n_boot: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Paired bootstrap of treatment effect:
    learned_win - v3_win per pair. ponytail:
    resample pairs with replacement, compute
    mean treatment effect.
    """
    # Build per-pair treatment outcomes: +1 if
    # learned won, -1 if V3 won, 0 if split.
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_win") is None:
            continue
        p = r.get("pair_id")
        s = r.get("side")
        by_pair.setdefault(p, {})[s] = r
    outcomes: List[float] = []
    for p, sides in by_pair.items():
        if "p1" not in sides or "p2" not in sides:
            continue
        d1, d2 = sides["p1"], sides["p2"]
        learned_d1 = bool(d1["our_win"])
        learned_d2 = not bool(d2["our_win"])
        if learned_d1 and learned_d2:
            outcomes.append(1.0)
        elif (not learned_d1) and (not learned_d2):
            outcomes.append(-1.0)
        else:
            outcomes.append(0.0)
    if not outcomes:
        return {
            "treatment_mean": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "n_pairs": 0,
        }
    rng = random.Random(seed)
    boot_means: List[float] = []
    n = len(outcomes)
    for _ in range(n_boot):
        sample = [outcomes[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    ci_low = boot_means[int(0.025 * n_boot)]
    ci_high = boot_means[int(0.975 * n_boot)]
    return {
        "treatment_mean": sum(outcomes) / n,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n_pairs": n,
    }


def _exact_sign_test(
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Two-sided exact sign test: count pairs
    where learned > V3 and learned < V3; ties are
    ignored. Use binomial test. ponytail: compute
    p-value via simple enumeration (small n).
    """
    from math import comb
    by_pair: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        if r.get("our_win") is None:
            continue
        p = r.get("pair_id")
        s = r.get("side")
        by_pair.setdefault(p, {})[s] = r
    plus = 0
    minus = 0
    for p, sides in by_pair.items():
        if "p1" not in sides or "p2" not in sides:
            continue
        d1, d2 = sides["p1"], sides["p2"]
        learned_d1 = bool(d1["our_win"])
        learned_d2 = not bool(d2["our_win"])
        if learned_d1 and learned_d2:
            plus += 1
        elif (not learned_d1) and (not learned_d2):
            minus += 1
    n = plus + minus
    if n == 0:
        return {
            "n_pairs": 0, "plus": 0, "minus": 0,
            "p_two_sided": 1.0,
        }
    k = min(plus, minus)
    # Two-sided exact binomial p-value.
    p_val = 0.0
    for i in range(0, k + 1):
        p_val += comb(n, i) * (0.5 ** n)
    p_val_two_sided = min(1.0, 2 * p_val)
    # One-sided p (learned < V3).
    p_one_sided = 0.0
    for i in range(0, plus + 1):
        p_one_sided += comb(n, i) * (0.5 ** n)
    return {
        "n_pairs": n,
        "plus": plus,
        "minus": minus,
        "p_two_sided": p_val_two_sided,
        "p_one_sided_learned_regression": p_one_sided,
    }


def _plan_change_rate(
    rows: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Plan change rate: how often does a policy
    pick a different plan across battles for the
    same team? ponytail: per-policy measure.
    """
    by_team_pol: Dict[Tuple[str, str], List] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        team_id = r.get("team_id", "")
        pol = r.get("our_policy", "")
        if not team_id or not pol:
            continue
        key = (team_id, pol)
        by_team_pol.setdefault(key, []).append(
            tuple(r.get("our_chosen_4", []))
        )
    rates: Dict[str, float] = {}
    for (team_id, pol), plans in by_team_pol.items():
        if len(plans) < 2:
            continue
        first = plans[0]
        diffs = sum(1 for p in plans if p != first)
        rates[pol] = diffs / len(plans)
    return rates


def _unique_plan_counts(
    rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Per-policy unique chosen_4 count.
    ponytail: simple set count.
    """
    by_pol: Dict[str, set] = {}
    for r in rows:
        if r.get("status") != "ok":
            continue
        pol = r.get("our_policy", "")
        if not pol:
            continue
        chosen = tuple(
            sorted(
                s.lower() for s in r.get("our_chosen_4", [])
            )
        )
        by_pol.setdefault(pol, set()).add(chosen)
    return {pol: len(s) for pol, s in by_pol.items()}


# ---------------------------------------------------------------------------
# Reality-check gates
# ---------------------------------------------------------------------------


def _reality_gates(
    validation: Dict[str, Any],
    cats: Dict[str, int],
    side_collapse: float,
    learned_total: int,
    learned_total_battles: int,
    treatment_mean: float,
) -> Dict[str, Any]:
    """Apply the V3c.2 spec's reality-check gates.
    """
    gates: Dict[str, bool] = {}
    gates["n_battles_eq_40"] = (
        validation["n_battles"] == 40
    )
    gates["n_complete_pairs_eq_20"] = (
        validation["n_complete_pairs"] == 20
    )
    gates["zero_bad_status"] = (
        validation["n_bad_status"] == 0
    )
    gates["preview_validation_100pct"] = (
        validation["n_chosen_4_ok"] == 40
        and validation["n_lead_2_ok"] == 40
        and validation["n_back_2_ok"] == 40
    )
    gates["side_collapse_le_15pp"] = side_collapse <= 0.15
    learned_wr = (
        learned_total / learned_total_battles
        if learned_total_battles else 0.0
    )
    gates["learned_win_rate_ge_0.50"] = learned_wr >= 0.50
    gates["learned_both_ge_v3_both"] = (
        cats["learned_both"] >= cats["v3_both"]
    )
    gates["treatment_effect_ge_0"] = treatment_mean >= 0.0
    overall = all(gates.values())
    return {
        "gates": gates,
        "overall_pass": overall,
        "learned_win_rate": learned_wr,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _build_report(
    tag: str,
    jsonl_path: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a complete V3c.2 report. ponytail:
    aggregator; reuses all helpers.
    """
    validation = _validate_v3c2(rows)
    cats = _paired_categories(rows)
    learned_p1, learned_p2, v3_p1, v3_p2 = _win_counts_by_side(
        rows
    )
    learned_total = learned_p1 + learned_p2
    v3_total = v3_p1 + v3_p2
    learned_total_battles = learned_total + v3_total
    learned_wr = (
        learned_total / learned_total_battles
        if learned_total_battles else 0.0
    )
    ci_low, ci_high = _wilson_ci(
        learned_total, learned_total_battles
    )
    # Side collapse: |learned_wr_p1 - learned_wr_p2|.
    p1_total = learned_p1 + v3_p1
    p2_total = learned_p2 + v3_p2
    if p1_total and p2_total:
        learned_wr_p1 = learned_p1 / p1_total
        learned_wr_p2 = learned_p2 / p2_total
        side_collapse = abs(learned_wr_p1 - learned_wr_p2)
    else:
        side_collapse = 0.0
    boot = _paired_bootstrap(rows)
    sign = _exact_sign_test(rows)
    plan_changes = _plan_change_rate(rows)
    unique_plans = _unique_plan_counts(rows)
    avg_turns = (
        sum(
            r.get("turns", 0) for r in rows
            if r.get("status") == "ok"
        )
        / max(1, validation["n_ok"])
    )
    gates = _reality_gates(
        validation, cats, side_collapse,
        learned_total, learned_total_battles,
        boot["treatment_mean"],
    )
    return {
        "tag": tag,
        "jsonl_path": jsonl_path,
        "validation": validation,
        "win_counts": {
            "learned_p1": learned_p1,
            "learned_p2": learned_p2,
            "v3_p1": v3_p1,
            "v3_p2": v3_p2,
            "learned_total": learned_total,
            "v3_total": v3_total,
            "learned_total_battles": learned_total_battles,
        },
        "learned_win_rate": learned_wr,
        "wilson_ci": [ci_low, ci_high],
        "side_collapse": side_collapse,
        "paired_categories": cats,
        "paired_bootstrap": boot,
        "exact_sign_test": sign,
        "treatment_effect": boot["treatment_mean"],
        "plan_change_rate": plan_changes,
        "unique_plan_counts": unique_plans,
        "avg_turns": avg_turns,
        "gates": gates,
    }


def _write_report_files(
    report: Dict[str, Any], json_path: str, md_path: str
) -> None:
    os.makedirs(os.path.dirname(json_path) or ".",
                exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    g = report["gates"]
    lines = [
        "# Phase V3c.2 — Reality Check",
        "",
        f"- tag: {report['tag']}",
        f"- jsonl_path: {report['jsonl_path']}",
        f"- n_battles: {report['validation']['n_battles']}",
        f"- n_complete_pairs: "
        f"{report['validation']['n_complete_pairs']}",
        f"- n_bad_status: {report['validation']['n_bad_status']}",
        f"- learned win rate: "
        f"{report['learned_win_rate']:.3f} "
        f"({report['win_counts']['learned_total']}/"
        f"{report['win_counts']['learned_total_battles']})",
        f"- Wilson 95% CI: "
        f"[{report['wilson_ci'][0]:.3f}, "
        f"{report['wilson_ci'][1]:.3f}]",
        f"- side_collapse: {report['side_collapse']:.3f}",
        f"- treatment_effect: "
        f"{report['treatment_effect']:.3f}",
        f"- paired_bootstrap CI: "
        f"[{report['paired_bootstrap']['ci_low']:.3f}, "
        f"{report['paired_bootstrap']['ci_high']:.3f}]",
        f"- exact sign test p (two-sided): "
        f"{report['exact_sign_test']['p_two_sided']:.3f}",
        f"- avg_turns: {report['avg_turns']:.1f}",
        "",
        "## Win counts by side",
        "",
        "| side | learned | V3 |",
        "|---|---:|---:|",
        f"| p1 | {report['win_counts']['learned_p1']} "
        f"| {report['win_counts']['v3_p1']} |",
        f"| p2 | {report['win_counts']['learned_p2']} "
        f"| {report['win_counts']['v3_p2']} |",
        "",
        "## Paired categories",
        "",
        "| category | count |",
        "|---|---:|",
        f"| learned_both | "
        f"{report['paired_categories']['learned_both']} |",
        f"| v3_both | {report['paired_categories']['v3_both']} |",
        f"| split | {report['paired_categories']['split']} |",
        f"| invalid | {report['paired_categories']['invalid']} |",
        "",
        "## Reality-check gates",
        "",
        "| gate | result |",
        "|---|:-:|",
    ]
    for k, v in g["gates"].items():
        lines.append(f"| {k} | {'PASS' if v else 'FAIL'} |")
    decision = (
        "GO_FOR_100_PAIR_QUALIFICATION"
        if g["overall_pass"] else "BLOCKED"
    )
    lines += [
        "",
        f"**OVERALL: {decision}**",
    ]
    with open(md_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase V3c.2 20-pair VGC reality check "
            "learned_preview_v3c1 vs matchup_top4_v3"
        )
    )
    parser.add_argument("--n-pairs", type=int, default=20)
    parser.add_argument("--start-pair", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--report-json",
        type=str,
        default=os.path.join(
            LOG_DIR,
            "vgc2026_phaseV3c2_reality_report.json",
        ),
    )
    parser.add_argument(
        "--report-md",
        type=str,
        default=os.path.join(
            LOG_DIR,
            "vgc2026_phaseV3c2_reality_report.md",
        ),
    )
    parser.add_argument(
        "--analyze-only", action="store_true",
        help="Skip running battles; only build report.",
    )
    args = parser.parse_args()
    err = preflight()
    if err is not None:
        print(f"ERROR preflight: {err}")
        return 4
    if not args.analyze_only:
        print(
            f"Phase V3c.2: {POLICY_LEARNED} vs "
            f"{POLICY_BASELINE}, n_pairs={args.n_pairs}"
        )
        out = run_v3c2_reality(
            n_pairs=args.n_pairs,
            start_pair=args.start_pair,
            seed=args.seed,
            timeout=args.timeout,
            overwrite=args.overwrite,
        )
        if "error" in out:
            print(f"ERROR: {out['error']}")
            return 5
        print(
            f"  {out['n_battles']} battles in "
            f"{out['elapsed_s']:.0f}s"
        )
    jsonl_path = os.path.join(LOG_DIR, f"vgc2026_{DEFAULT_TAG}.jsonl")
    rows = _load_jsonl(jsonl_path)
    if not rows:
        print(f"ERROR: no rows in {jsonl_path}")
        return 6
    report = _build_report(DEFAULT_TAG, jsonl_path, rows)
    _write_report_files(
        report, args.report_json, args.report_md
    )
    decision = (
        "GO_FOR_100_PAIR_QUALIFICATION"
        if report["gates"]["overall_pass"] else "BLOCKED"
    )
    print(
        f"\n{'='*60}\n"
        f"V3c.2: overall = {decision}\n"
        f"  learned win rate = "
        f"{report['learned_win_rate']:.3f}\n"
        f"  side collapse = {report['side_collapse']:.3f}\n"
        f"{'='*60}"
    )
    return 0 if report["gates"]["overall_pass"] else 7


if __name__ == "__main__":
    sys.exit(main())
