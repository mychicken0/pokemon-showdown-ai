#!/usr/bin/env python3
"""Phase V3a.2 — Small Battle Reality Check.

Runs 20 paired battles (D1: learned_preview_v3a1 vs V3,
D2: V3 vs learned_preview_v3a1) on localhost:8000.

Reuses the existing ControlledTeamPreviewPlayer
from ``bot_vgc2026_phaseV2c`` so the runtime engine
is identical to other VGC runs. The only difference
is the preview policy (V3 vs learned_preview_v3a1).

No large benchmark. Health check first. Refuses to
overwrite existing artifacts.
"""
import argparse
import asyncio
import atexit
import csv
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Unregister poke-env's broken atexit hook.
import poke_env.concurrency
_clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if _clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import poke_env_test_cleanup  # noqa: F401

from poke_env import AccountConfiguration

from bot_vgc2026_phaseV2c import (
    ControlledTeamPreviewPlayer,
    PreviewResult,
    build_team_string,
    validate_team_for_battle,
)
from team_preview_policy import choose_four_from_six
from vgc_team_pool import load_vgc_pool


HEALTH_URL = "http://localhost:8000"
HEALTH_TIMEOUT = 3.0
DEFAULT_TAG = "phaseV3a2_reality20"
ACCOUNT_PREFIX = "V3a2_"
BATTLE_FORMAT = "gen9championsvgc2026regma"


def check_localhost(timeout: float = HEALTH_TIMEOUT) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def pick_preview(
    team: List[Dict[str, Any]],
    policy: str,
    opponent_team: Optional[List[Dict[str, Any]]] = None,
    seed: int = 42,
) -> PreviewResult:
    """Wrap choose_four_from_six for one policy."""
    return choose_four_from_six(
        team, opponent_team=opponent_team, policy=policy, seed=seed
    )


SHOWDOWN_NAME_MAX = 18


def _sanitize_run_id(raw: Optional[str]) -> str:
    """Phase BI-3K.5: sanitize a user-supplied run id.

    Allows alphanumeric only, caps at 4 chars, returns "" for
    falsy input. Raises ``ValueError`` if the input has any
    non-alphanumeric character (so users see a clear error
    rather than silent name corruption).
    """
    if not raw:
        return ""
    s = str(raw)
    if not s.isalnum():
        raise ValueError(
            f"--account-run-id must be alphanumeric, got {s!r}"
        )
    if len(s) > 4:
        raise ValueError(
            f"--account-run-id must be <=4 chars, got {len(s)}: {s!r}"
        )
    return s


def _showdown_normalize(name: str) -> str:
    """Phase BI-3K.6: Showdown userid normalization.

    Showdown stores userids as lowercase alphanumeric
    only. A pair like ``Foo_Bar123`` and ``foobar12`` would
    collide server-side even if the visible account name
    is different. This helper mirrors that normalization
    so the preflight uniqueness check catches such
    collisions before connecting.
    """
    return "".join(c for c in name.lower() if c.isalnum())


def preflight_uniqueness_check(
    n_pairs: int, start_pair: int,
    prefix: str, account_run_id: str,
) -> Dict[Tuple[int, str, str], str]:
    """Phase BI-3K.6: generate all 4 account names per pair.

    For each pair_id in the requested range, produce:
      - d1 p1 treatment (L)
      - d1 p2 baseline (V)
      - d2 p1 baseline (V)
      - d2 p2 treatment (L)

    Returns a dict mapping ``(pair_id, day, side)`` to the
    resolved name. Raises ``ValueError`` with the full
    list of collisions if any duplicate appears (compared
    after Showdown userid normalization: lowercase
    alphanumeric only).
    """
    out: Dict[Tuple[int, str, str], str] = {}
    for offset in range(n_pairs):
        pid = start_pair + offset
        for day, side, learned in (
            ("d1", "p1", True),
            ("d1", "p2", False),
            ("d2", "p1", False),
            ("d2", "p2", True),
        ):
            name = make_player_name(
                pair_id=pid, side=side, learned=learned,
                prefix=prefix, account_run_id=account_run_id,
            )
            out[(pid, day, side)] = name
    # Compare by Showdown-normalized userid to catch
    # case-insensitive / punctuation collisions.
    seen: Dict[str, List[Tuple[int, str, str]]] = {}
    for key, name in out.items():
        norm = _showdown_normalize(name)
        seen.setdefault(norm, []).append((key, name))
    dups = {
        n: [(k, nm) for k, nm in v]
        for n, v in seen.items() if len(v) > 1
    }
    if dups:
        msg = (
            f"Account name collision detected for "
            f"{n_pairs} pairs starting at {start_pair} "
            f"with prefix={prefix!r}, run_id="
            f"{account_run_id!r}. Duplicates "
            f"(Showdown-normalized):\n"
        )
        for n, entries in dups.items():
            msg += f"  {n!r}:\n"
            for key, nm in entries:
                msg += f"    {key} -> {nm!r}\n"
        raise ValueError(msg)
    return out


def make_player_name(
    pair_id: int, side: str, learned: bool,
    prefix: str = ACCOUNT_PREFIX,
    account_run_id: str = "",
) -> str:
    """Generate a stable player account name.

    ponytail: ``prefix`` parameter added for
    multi-version runs (e.g. V3c.2 uses
    ``V3c2_``). Default preserves the V3a.2
    behavior.

    Phase BI-3K.5: when ``account_run_id`` is provided,
    the name is ``<prefix><runid>p<NNN><side_digit><L/V>``
    where ``NNN = pair_id % 1000``. The 18-char Showdown
    limit is enforced explicitly: a name that would exceed
    18 chars raises ``ValueError`` BEFORE connecting,
    rather than being silently truncated. When
    ``account_run_id`` is empty, the old behavior is
    preserved exactly (including its silent 18-char
    truncation for backward compatibility).
    """
    suffix = "L" if learned else "V"
    if not account_run_id:
        # Backward-compatible path: identical to the old
        # output, including the silent 18-char slice.
        return f"{prefix}p{pair_id:02d}_{side}{suffix}"[:18]
    # New run-id path: explicit length check, no truncation.
    side_digit = "1" if side == "p1" else "2"
    name = (
        f"{prefix}{account_run_id}p{pair_id % 1000:03d}"
        f"{side_digit}{suffix}"
    )
    if len(name) > SHOWDOWN_NAME_MAX:
        raise ValueError(
            f"Generated account name {name!r} is "
            f"{len(name)} chars, exceeds Showdown limit "
            f"of {SHOWDOWN_NAME_MAX}. Use a shorter "
            f"--account-prefix or --account-run-id."
        )
    return name


def resolve_artifact_paths(log_dir: Path, tag: str) -> Tuple[Path, Path]:
    csv_path = log_dir / f"vgc2026_{tag}.csv"
    jsonl_path = log_dir / f"vgc2026_{tag}.jsonl"
    return csv_path, jsonl_path


def init_artifacts(tag: str, overwrite: bool) -> Tuple[Path, Path, Dict[str, Any]]:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    csv_path, jsonl_path = resolve_artifact_paths(log_dir, tag)
    if (csv_path.exists() or jsonl_path.exists()) and not overwrite:
        raise FileExistsError(
            f"Artifacts already exist for tag '{tag}': "
            f"csv={csv_path.exists()}, jsonl={jsonl_path.exists()}. "
            f"Use --overwrite to replace."
        )
    # Write headers.
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "pair_id", "side", "our_policy", "opponent_policy",
            "battle_tag", "started_at", "finished_at",
            "status", "our_win", "turns", "error_detail",
            "our_chosen_4", "our_lead_2", "our_back_2",
            "opp_chosen_4", "opp_lead_2", "opp_back_2",
        ])
    open(jsonl_path, "w").close()
    return csv_path, jsonl_path, {"tag": tag}


def build_treatment_player_config(
    is_treatment: bool, enable_mega_evolution: bool
):
    """Phase BI-3K.3: tiny pure helper.

    Returns a ``DoublesDamageAwareConfig(enable_mega_evolution=True)``
    iff both ``is_treatment`` and ``enable_mega_evolution`` are True.
    Otherwise returns None — the caller should leave the config
    unset so the bot falls back to the global default
    (``enable_mega_evolution=False``).

    The treatment/learned arm is the bot that uses
    ``learned_policy`` in the current battle. This helper
    intentionally does NOT decide which side is treatment —
    the runner passes that decision in. It is a pure
    config-builder.

    Keeping the helper tiny and pure makes it easy to unit
    test the wiring rule without spinning up poke-env.
    """
    if not (is_treatment and enable_mega_evolution):
        return None
    # Local import to keep top-level imports lean.
    from bot_doubles_damage_aware import (
        DoublesDamageAwareConfig,
    )
    return DoublesDamageAwareConfig(enable_mega_evolution=True)


def build_treatment_player_config_with_timing(
    base_config, enable_decision_timing_diagnostics: bool
):
    """Phase RUNNER-TIMING-1: tiny pure helper.

    Returns a config that combines ``base_config`` (which
    may be None, a Mega-only config, or a piecewise config
    from BEHAVIOR-15) with timing diagnostics. Only modifies
    the base when ``enable_decision_timing_diagnostics`` is
    True. The flag is independent of Mega and piecewise.

    If the base is None, returns a fresh config with timing
    on. If the base is set, merges the timing flag into a
    new DoublesDamageAwareConfig (preserving all other
    fields, including Mega / piecewise).

    Default OFF (False) returns the base unchanged so
    production behavior is preserved.
    """
    from bot_doubles_damage_aware import (
        DoublesDamageAwareConfig,
    )
    if not enable_decision_timing_diagnostics:
        return base_config
    if base_config is None:
        return DoublesDamageAwareConfig(
            enable_decision_timing_diagnostics=True
        )
    return DoublesDamageAwareConfig(
        **{
            **base_config.__dict__,
            "enable_decision_timing_diagnostics": True,
        }
    )


async def run_one_battle(
    pair_id: int,
    side: str,
    player_policy: str,
    opponent_policy: str,
    our_team_idx: int,
    opp_team_idx: int,
    pool: Any,
    seed: int = 42,
    timeout: float = 90.0,
    learned_policy: str = "learned_preview_v3a1",
    account_prefix: str = ACCOUNT_PREFIX,
    account_run_id: str = "",
    enable_mega_evolution: bool = False,
    enable_behavior_15_piecewise: bool = False,
    enable_decision_timing_diagnostics: bool = False,
    audit_logger_treatment=None,
    audit_logger_baseline=None,
) -> Dict[str, Any]:
    """Run one VGC battle: our team at our_team_idx uses
    player_policy, opponent uses opponent_policy.
    """
    our_team_row = pool.get_team(our_team_idx)
    opp_team_row = pool.get_team(opp_team_idx)
    if our_team_row is None or opp_team_row is None:
        return {
            "pair_id": pair_id, "side": side,
            "our_policy": player_policy,
            "opponent_policy": opponent_policy,
            "status": "no_team", "our_win": None, "turns": 0,
            "error_detail": f"team lookup failed: our={our_team_idx} opp={opp_team_idx}",
        }
    our_team = our_team_row.pokemon
    opp_team = opp_team_row.pokemon
    # Pick previews.
    our_preview = pick_preview(
        our_team, player_policy,
        opponent_team=opp_team, seed=seed,
    )
    opp_preview = pick_preview(
        opp_team, opponent_policy,
        opponent_team=our_team, seed=seed + 1,
    )
    # Build showdown-format team strings. VGC format
    # requires a custom team.
    our_team_str = build_team_string(our_team, our_preview.chosen_4)
    opp_team_str = build_team_string(opp_team, opp_preview.chosen_4)
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
    # Player names.
    # ponytail: ``learned_policy`` is a parameter so
    # multi-version runs (e.g. V3c.1) can reuse this
    # runner without the V3a.1 hardcode.
    is_learned_first = (
        side == "p1" and player_policy == learned_policy
    )
    is_learned_second = (
        side == "p2" and player_policy == learned_policy
    )
    p1_name = make_player_name(
        pair_id, "p1", is_learned_first,
        prefix=account_prefix, account_run_id=account_run_id,
    )
    p2_name = make_player_name(
        pair_id, "p2", is_learned_second,
        prefix=account_prefix, account_run_id=account_run_id,
    )
    # Phase BI-3K.6: treatment is the side argument, NOT
    # inferred from policy equality. Mega ON/OFF can
    # intentionally use the same policy string on both
    # arms, so policy-based inference is wrong. In this
    # paired runner, side=="p1" means p1 is treatment;
    # side=="p2" means p2 is treatment.
    p1_is_treatment = (side == "p1")
    p2_is_treatment = (side == "p2")
    is_treatment = p1_is_treatment or p2_is_treatment
    treatment_config = build_treatment_player_config(
        is_treatment, enable_mega_evolution
    )
    # Phase BEHAVIOR-15: opt-in piecewise. Only
    # applied to the treatment arm when the CLI
    # flag is set. Default OFF keeps production
    # scoring unchanged.
    if is_treatment and enable_behavior_15_piecewise:
        from bot_doubles_damage_aware import (
            DoublesDamageAwareConfig,
        )
        piecewise_cfg = DoublesDamageAwareConfig(
            enable_speed_priority_piecewise_expected_faint_policy=True
        )
        if treatment_config is None:
            treatment_config = piecewise_cfg
        else:
            # Merge piecewise into existing treatment_config.
            treatment_config = DoublesDamageAwareConfig(
                **{
                    **treatment_config.__dict__,
                    "enable_speed_priority_piecewise_expected_faint_policy": True,
                }
            )
    # Phase RUNNER-TIMING-1: opt-in timing diagnostics.
    # Independent of Mega / piecewise. Default OFF keeps
    # production scoring unchanged. When set, treatment
    # bot records decision_time_ms / valid_order_time_ms /
    # score_action_time_ms in the audit JSONL.
    if is_treatment:
        treatment_config = (
            build_treatment_player_config_with_timing(
                treatment_config,
                enable_decision_timing_diagnostics,
            )
        )
    # Phase BI-3K.6: build BOTH p1_kwargs and p2_kwargs
    # completely BEFORE constructing either player. Each
    # side must call ControlledTeamPreviewPlayer(...) exactly
    # once. The previous pattern (construct, then add config,
    # then reconstruct) caused duplicate constructions and
    # contributed to the |nametaken| collisions seen in
    # BI-3K.4 / BI-3K.4b / BI-3K.5.
    p1_kwargs = dict(
        account_configuration=AccountConfiguration(p1_name, None),
        preview_result=our_preview if side == "p1" else opp_preview,
        battle_tag=f"battle-gen9vgc2026regma-{pair_id:03d}-{side}",
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        log_level=30,
        team=our_team_str if side == "p1" else opp_team_str,
    )
    p2_kwargs = dict(
        account_configuration=AccountConfiguration(p2_name, None),
        preview_result=opp_preview if side == "p1" else our_preview,
        battle_tag=f"battle-gen9vgc2026regma-{pair_id:03d}-{side}",
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        log_level=30,
        team=opp_team_str if side == "p1" else our_team_str,
    )
    # Phase BI-3K.6: attach Mega config and audit logger
    # ONLY to the treatment side. Baseline side gets no
    # config override. Both sides DO get an audit logger
    # (when --audit-decisions is set) so baseline arm
    # integrity can be verified at runtime. The loggers
    # are distinct instances writing to distinct files;
    # attaching both is observational only and does not
    # affect scoring or selection.
    if p1_is_treatment:
        if treatment_config is not None:
            p1_kwargs["config"] = treatment_config
        if audit_logger_treatment is not None:
            p1_kwargs["audit_logger"] = audit_logger_treatment
    else:
        if audit_logger_baseline is not None:
            p1_kwargs["audit_logger"] = audit_logger_baseline
    if p2_is_treatment:
        if treatment_config is not None:
            p2_kwargs["config"] = treatment_config
        if audit_logger_treatment is not None:
            p2_kwargs["audit_logger"] = audit_logger_treatment
    else:
        if audit_logger_baseline is not None:
            p2_kwargs["audit_logger"] = audit_logger_baseline
    # Phase BI-3K.6: single construction. Each player is
    # built exactly once with its complete kwargs.
    p1 = ControlledTeamPreviewPlayer(**p1_kwargs)
    p2 = ControlledTeamPreviewPlayer(**p2_kwargs)
    if side == "p2":
        p1.preview_result = opp_preview
        p2.preview_result = our_preview
    started = datetime.utcnow().isoformat()
    battle_tag = f"battle-gen9vgc2026regma-{pair_id:03d}-{side}"
    status = "ok"
    error_detail = ""
    our_win: Optional[bool] = None
    turns = 0
    # Phase BI-3K.7: set context-based battle metadata on
    # BOTH audit loggers (treatment and baseline) before
    # the battle starts. The treatment logger gets
    # benchmark_arm="treatment" and enable_mega_evolution
    # reflects whether the treatment config was attached.
    # The baseline logger gets benchmark_arm="baseline" and
    # enable_mega_evolution=False (baseline never gets the
    # treatment config). player_side and player_name are
    # recorded so the persisted row identifies which side
    # the audit came from. Both loggers are set so that
    # save_battle (called on whichever player is the audit
    # writer) always finds its context.
    baseline_side = "p2" if side == "p1" else "p1"
    baseline_name = p2_name if side == "p1" else p1_name
    if audit_logger_treatment is not None and hasattr(
        audit_logger_treatment, "set_current_battle_meta"
    ):
        audit_logger_treatment.set_current_battle_meta(
            benchmark_arm="treatment",
            enable_mega_evolution=(treatment_config is not None and bool(
                getattr(
                    treatment_config,
                    "enable_mega_evolution",
                    False,
                )
            )),
            enable_decision_timing_diagnostics=bool(
                enable_decision_timing_diagnostics
            ),
            treatment_side=side,
            player_side=side,
            player_name=(
                p1_name if side == "p1" else p2_name
            ),
        )
    if audit_logger_baseline is not None and hasattr(
        audit_logger_baseline, "set_current_battle_meta"
    ):
        audit_logger_baseline.set_current_battle_meta(
            benchmark_arm="baseline",
            enable_mega_evolution=False,
            enable_decision_timing_diagnostics=bool(
                enable_decision_timing_diagnostics
            ),
            treatment_side=baseline_side,
            player_side=baseline_side,
            player_name=baseline_name,
        )
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
            # Determine "our win" based on the side.
            if side == "p1":
                our_win = bool(p1_wins and not p2_wins)
            else:
                our_win = bool(p2_wins and not p1_wins)
            # Pull turns from the battle object.
            for bt, b in p1.battles.items():
                turns = max(turns, int(getattr(b, "turn", 0) or 0))
                break
    except asyncio.TimeoutError:
        status = "timeout"
        error_detail = f"timeout after {timeout}s"
    except Exception as e:
        status = "error"
        error_detail = f"{type(e).__name__}: {e}"
    finally:
        for pl in (p1, p2):
            try:
                if hasattr(pl, "ps_client") and hasattr(
                    pl.ps_client, "_stop_listening"
                ):
                    await pl.ps_client._stop_listening()
            except Exception:
                pass
    finished_at = datetime.utcnow().isoformat()
    return {
        "pair_id": pair_id, "side": side,
        "our_policy": player_policy,
        "opponent_policy": opponent_policy,
        "battle_tag": battle_tag,
        "started_at": started, "finished_at": finished_at,
        "status": status, "our_win": our_win, "turns": turns,
        "error_detail": error_detail,
        # Phase BI-3K.3: minimal audit metadata so future
        # reports can distinguish treatment vs baseline and
        # verify Mega config assignment per side.
        "benchmark_arm": (
            "treatment" if is_treatment else "baseline"
        ),
        "enable_mega_evolution": bool(
            treatment_config is not None
            and bool(getattr(
                treatment_config,
                "enable_mega_evolution",
                False,
            ))
        ),
        # Phase RUNNER-TIMING-1: timing diagnostics
        # flag recorded per battle so future reports
        # can identify which runs had timing on.
        "enable_decision_timing_diagnostics": bool(
            enable_decision_timing_diagnostics
        ),
        "treatment_side": side if is_treatment else "",
        # Phase BI-3K.5: resolved account names and run id
        # so analysis can identify the exact accounts used.
        "p1_name": p1_name,
        "p2_name": p2_name,
        "account_run_id": account_run_id,
        "our_chosen_4": our_preview.chosen_4,
        "our_lead_2": our_preview.lead_2,
        "our_back_2": our_preview.back_2,
        "opp_chosen_4": opp_preview.chosen_4,
        "opp_lead_2": opp_preview.lead_2,
        "opp_back_2": opp_preview.back_2,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Phase V3a.2 VGC preview reality check"
    )
    parser.add_argument(
        "--tag", type=str, default=DEFAULT_TAG,
        help="Artifact tag (default: phaseV3a2_reality20).",
    )
    parser.add_argument(
        "--n-pairs", type=int, default=20,
        help="Number of pairs (default: 20).",
    )
    parser.add_argument(
        "--start-pair", type=int, default=0,
        help="Starting pair_id for chunked runs "
        "(default: 0). Team indices are "
        "pair_id %% pool_size, so chunks compose.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Deterministic seed (default: 42).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifacts.",
    )
    parser.add_argument(
        "--timeout", type=float, default=90.0,
        help="Per-battle timeout in seconds (default: 90).",
    )
    parser.add_argument(
        "--learned-policy", type=str,
        default="learned_preview_v3a1",
        help=(
            "Learned-arm policy. Default V3a.1; pass "
            "e.g. learned_preview_v3c1 for V3c.2."
        ),
    )
    parser.add_argument(
        "--account-prefix", type=str,
        default=ACCOUNT_PREFIX,
        help=(
            "Visible account-name prefix. Default "
            "V3a2_; pass e.g. V3c2_ for V3c.2."
        ),
    )
    parser.add_argument(
        "--account-run-id", type=str, default="",
        help=(
            "Phase BI-3K.5: optional short run id "
            "(alphanumeric, <=4 chars) embedded in the "
            "account name to avoid |nametaken| collisions "
            "across repeated local runs. Default empty "
            "preserves the original naming behavior."
        ),
    )
    parser.add_argument(
        "--enable-mega-evolution", action="store_true",
        help=(
            "Phase BI-3E probe: enable Mega legal-order "
            "generation on the learned-arm bot (p1). "
            "Default OFF. Does NOT change the global "
            "DoublesDamageAwareConfig default; only the "
            "p1 instance in this probe run."
        ),
    )
    parser.add_argument(
        "--enable-behavior-15-piecewise", action="store_true",
        help=(
            "Phase BEHAVIOR-15 probe: enable opt-in "
            "piecewise expected-faint attack penalty "
            "on the treatment arm. Default OFF. Does "
            "NOT change the global "
            "DoublesDamageAwareConfig default; only "
            "the treatment-arm instance in this probe."
        ),
    )
    parser.add_argument(
        "--audit-decisions", action="store_true",
        help=(
            "Phase BI-3F-1 probe: attach a "
            "DoublesDecisionAuditLogger to the learned-arm "
            "bot so per-turn audit JSONL is persisted "
            "(v4a legal/selected/final keys, "
            "state_snapshot, switch_counterfactual, etc.). "
            "Default OFF. Path: "
            "logs/vgc2026_<tag>_audit.jsonl. Does NOT "
            "change scoring or selection."
        ),
    )
    parser.add_argument(
        "--enable-timing-diagnostics", action="store_true",
        help=(
            "Phase RUNNER-TIMING-1 probe: enable "
            "decision-timing diagnostics on the "
            "treatment-arm bot. Persists "
            "decision_time_ms / valid_order_time_ms / "
            "score_action_time_ms in the audit JSONL. "
            "Default OFF. Does NOT change scoring or "
            "selection. Independent of "
            "--enable-mega-evolution and "
            "--enable-behavior-15-piecewise. Only takes "
            "effect when --audit-decisions is also set."
        ),
    )
    args = parser.parse_args()

    if not check_localhost():
        print("ERROR: localhost:8000 not healthy. Refusing to run.")
        sys.exit(3)
    csv_path, jsonl_path, paths_meta = init_artifacts(
        args.tag, args.overwrite
    )
    # Phase BI-3F-1: opt-in audit logger. One file per run
    # tag. Constructed once at run start with reset=True so
    # subsequent battles append. The logger is attached only
    # to the learned-arm bot; the baseline opponent uses the
    # default (no logger) path. Default OFF (no logger when
    # --audit-decisions is omitted).
    # Phase BI-3K.7: when --audit-decisions is set, create
    # TWO audit loggers — one for the treatment arm, one
    # for the baseline arm — each writing to its own file.
    # This is observational only and does not affect
    # scoring or selection. The treatment logger is
    # attached to whichever side is the treatment arm in
    # each run_one_battle call; the baseline logger goes
    # to the other side. Both files always exist (when
    # the flag is set) so analysis can compare them
    # directly without reconstructing which side was
    # which from the winner name.
    audit_logger_treatment = None
    audit_logger_baseline = None
    audit_path_treatment = None
    audit_path_baseline = None
    if args.audit_decisions:
        from doubles_decision_audit_logger import (
            DoublesDecisionAuditLogger,
        )
        audit_path_treatment = os.path.join(
            "logs", f"vgc2026_{args.tag}_treatment_audit.jsonl"
        )
        audit_path_baseline = os.path.join(
            "logs", f"vgc2026_{args.tag}_baseline_audit.jsonl"
        )
        audit_logger_treatment = DoublesDecisionAuditLogger(
            filepath=audit_path_treatment,
            reset=True,
            detail_level="top5",
        )
        audit_logger_baseline = DoublesDecisionAuditLogger(
            filepath=audit_path_baseline,
            reset=True,
            detail_level="top5",
        )
    print(
        f"Phase V3a.2 reality check: tag={args.tag}, "
        f"n_pairs={args.n_pairs}, learned_policy={args.learned_policy}"
        + (
            ", enable_mega_evolution=True (BI-3E probe)"
            if args.enable_mega_evolution
            else ""
        )
        + (
            ", audit_decisions=True (BI-3F-1 probe)"
            if args.audit_decisions
            else ""
        )
        + (
            ", enable_timing_diagnostics=True "
            "(RUNNER-TIMING-1 probe)"
            if args.enable_timing_diagnostics
            else ""
        )
    )
    print(f"  CSV    : {csv_path}")
    print(f"  JSONL  : {jsonl_path}")
    if audit_logger_treatment is not None:
        print(f"  AUDIT-T: {audit_path_treatment}")
        print(f"  AUDIT-B: {audit_path_baseline}")
    pool = load_vgc_pool()
    # Stable team indices.
    my_count = len(pool)
    opp_count = len(pool)
    results: List[Dict[str, Any]] = []
    start_time = time.time()
    # Phase BI-3K.5: sanitize run id and run preflight
    # uniqueness check before any connection.
    account_run_id = _sanitize_run_id(args.account_run_id)
    preflight_uniqueness_check(
        n_pairs=args.n_pairs, start_pair=args.start_pair,
        prefix=args.account_prefix,
        account_run_id=account_run_id,
    )

    # ponytail: single asyncio.run() entrypoint
    # (Phase V3c.2 fix). One event loop, sequential
    # awaits, no nested asyncio.run() calls that
    # previously caused poke_env background task
    # leaks.
    async def _run_all_pairs():
        nonlocal results
        for pair_id in range(
            args.start_pair, args.start_pair + args.n_pairs
        ):
            our_idx = pair_id % my_count
            opp_idx = pair_id % opp_count
            d1 = await run_one_battle(
                pair_id, "p1",
                args.learned_policy, "matchup_top4_v3",
                our_idx, opp_idx, pool, seed=args.seed,
                timeout=args.timeout,
                learned_policy=args.learned_policy,
                account_prefix=args.account_prefix,
                account_run_id=account_run_id,
                enable_mega_evolution=args.enable_mega_evolution,
                enable_behavior_15_piecewise=args.enable_behavior_15_piecewise,
                enable_decision_timing_diagnostics=(
                    args.enable_timing_diagnostics
                ),
                audit_logger_treatment=audit_logger_treatment,
                audit_logger_baseline=audit_logger_baseline,
            )
            d2 = await run_one_battle(
                pair_id, "p2",
                "matchup_top4_v3", args.learned_policy,
                our_idx, opp_idx, pool, seed=args.seed,
                timeout=args.timeout,
                learned_policy=args.learned_policy,
                account_prefix=args.account_prefix,
                account_run_id=account_run_id,
                enable_mega_evolution=args.enable_mega_evolution,
                enable_behavior_15_piecewise=args.enable_behavior_15_piecewise,
                enable_decision_timing_diagnostics=(
                    args.enable_timing_diagnostics
                ),
                audit_logger_treatment=audit_logger_treatment,
                audit_logger_baseline=audit_logger_baseline,
            )
            results.extend([d1, d2])
            # Write CSV row.
            with open(csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                for r in (d1, d2):
                    writer.writerow([
                        r["pair_id"], r["side"], r["our_policy"],
                        r["opponent_policy"], r["battle_tag"],
                        r["started_at"], r["finished_at"],
                        r["status"], r["our_win"], r["turns"],
                        r["error_detail"], "|".join(r["our_chosen_4"]),
                        "|".join(r["our_lead_2"]),
                        "|".join(r["our_back_2"]),
                        "|".join(r["opp_chosen_4"]),
                        "|".join(r["opp_lead_2"]),
                        "|".join(r["opp_back_2"]),
                    ])
            # Write JSONL row.
            with open(jsonl_path, "a") as f:
                f.write(json.dumps(d1) + "\n")
                f.write(json.dumps(d2) + "\n")
            elapsed = time.time() - start_time
            print(
                f"  pair {pair_id:02d} done ({elapsed:.0f}s elapsed) | "
                f"D1: {d1['status']}/{d1['our_win']} | "
                f"D2: {d2['status']}/{d2['our_win']}"
            )
        return results

    results = asyncio.run(_run_all_pairs())
    print(
        f"\n[done] {len(results)} battles in "
        f"{time.time() - start_time:.0f}s"
    )
    print(f"  Next: analyze:")
    print(
        f"    ./venv/bin/python "
        f"analyze_vgc2026_phaseV3a2_reality.py --tag {args.tag}"
    )


if __name__ == "__main__":
    main()
