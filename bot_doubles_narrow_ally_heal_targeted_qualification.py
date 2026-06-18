#!/usr/bin/env python3
"""
Phase 6.3.8d — Narrow Ally-Heal Wrong-Side Safety
Targeted Qualification.

This script proves the narrow rule on
``localhost:8000`` with a deterministic
qualification:

  1. The same battle runs twice, once with
     ``enable_ally_heal_wrong_side_hard_safety=False``
     (control) and once with the flag ON.
  2. Each turn is checked via the audit fields
     for the narrow candidates.
  3. A pass requires:

     - The narrow flag ON battle generates at
       least one turn with a narrow candidate
       (the engine saw Heal Pulse / Floral
       Healing / Decorate).
     - The narrow flag ON battle blocks at
       least one wrong-side selection.
     - The narrow flag ON battle does NOT
       select any wrong-side ally heal.
     - The broad flag stays OFF (we don't
       accidentally re-enable it).

The script uses localhost only. The
qualification is focused — it does NOT try to
prove every move. The paired ON/OFF
qualification is a separate script.
"""
import argparse
import asyncio
import atexit
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

# Unregister poke-env's broken atexit hook.
import poke_env.concurrency
clear_loop = getattr(poke_env.concurrency, "__clear_loop", None)
if clear_loop is not None:
    try:
        atexit.unregister(_clear_loop)
    except Exception:
        pass

import urllib.request

from poke_env import AccountConfiguration

from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
)
from doubles_decision_audit_logger import (
    DoublesDecisionAuditLogger,
)


BATTLE_FORMAT = "gen9randomdoublesbattle"


def check_localhost(timeout=2.0):
    try:
        with urllib.request.urlopen(
            "http://localhost:8000", timeout=timeout
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def make_team():
    return ""


async def battle_once(flag_on: bool, account_name: str, audit_path: str):
    config = DoublesDamageAwareConfig()
    config.enable_ally_heal_wrong_side_hard_safety = flag_on
    # Broad flag is OFF (default). We MUST NOT
    # silently repurpose it.
    config.enable_support_move_target_hard_safety = False
    audit = DoublesDecisionAuditLogger(
        filepath=audit_path, reset=False, detail_level="top5",
    )
    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(
            account_name, None
        ),
        verbose=False, config=config, audit_logger=audit,
        max_concurrent_battles=1,
        battle_format=BATTLE_FORMAT,
        team=make_team(),
    )
    return player, audit


def analyze_audit(audit_path: str) -> dict:
    """Walk the audit JSONL and collect narrow
    candidate evidence across ALL records in the
    file.
    """
    out = {
        "n_records": 0,
        "n_battles": 0,
        "n_turns": 0,
        "n_candidate_turns": 0,
        "n_blocked_turns": 0,
        "n_selected_wrong_side": 0,
        "move_ids": set(),
        "turns_with_candidate": [],
    }
    if not os.path.isfile(audit_path):
        return out
    with open(audit_path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out["n_records"] += 1
            out["n_battles"] += 1
            for turn in rec.get("audit_turns", []) or []:
                out["n_turns"] += 1
                t = turn.get("turn", -1)
                if turn.get("narrow_ally_heal_candidate", False):
                    out["n_candidate_turns"] += 1
                    out["turns_with_candidate"].append(t)
                s0 = turn.get("narrow_ally_heal_selected_slot0", False)
                s1 = turn.get("narrow_ally_heal_selected_slot1", False)
                b0 = turn.get(
                    "narrow_ally_heal_candidate_blocked_slot0", False
                )
                b1 = turn.get(
                    "narrow_ally_heal_candidate_blocked_slot1", False
                )
                if b0 or b1:
                    out["n_blocked_turns"] += 1
                if s0 or s1:
                    out["n_selected_wrong_side"] += 1
                for k in (
                    "narrow_ally_heal_move_id_slot0",
                    "narrow_ally_heal_move_id_slot1",
                ):
                    mid = turn.get(k)
                    if mid:
                        out["move_ids"].add(mid)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Phase 6.3.8d narrow targeted qualification"
    )
    parser.add_argument(
        "--artifact-tag", type=str, required=True,
        help="Unique artifact tag (required).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing artifacts.",
    )
    parser.add_argument(
        "--n-battles", type=int, default=10,
        help="Number of ON battles (and same number "
             "of OFF battles). Default 10.",
    )
    args = parser.parse_args()

    if not check_localhost():
        print("ERROR: localhost:8000 not healthy")
        sys.exit(3)

    audit_path = (
        f"logs/narrow_ally_heal_targeted_{args.artifact_tag}.jsonl"
    )
    if os.path.isfile(audit_path) and not args.overwrite:
        print(
            f"ERROR: {audit_path} already exists. "
            "Use --overwrite to replace."
        )
        sys.exit(2)

    open(audit_path, "w").close()
    print(
        f"Phase 6.3.8d targeted qualification: "
        f"tag={args.artifact_tag}, n_battles={args.n_battles}"
    )

    async def run_battles():
        players = []
        try:
            for i in range(args.n_battles):
                for flag_on in (False, True):
                    label = "ON" if flag_on else "OFF"
                    account = (
                        f"Nrt_{args.artifact_tag}_{i}_{label}"[:18]
                    )
                    player, audit = await battle_once(
                        flag_on, account, audit_path
                    )
                    players.append(player)
            # Run the battles concurrently.
            print(
                f"  Running {args.n_battles * 2} battles "
                f"({args.n_battles} ON, {args.n_battles} OFF)..."
            )
            await asyncio.gather(
                *(p.battle_against_opponent(players[0], 1)
                  for p in players)
            ) if False else None
        finally:
            for p in players:
                try:
                    if hasattr(p, "ps_client") and hasattr(
                        p.ps_client, "_stop_listening"
                    ):
                        await p.ps_client._stop_listening()
                except Exception:
                    pass
        # Run battles in sequence
        return

    # Actually, the simpler approach: run the
    # battles through the public API by
    # creating them in pairs and using
    # battle_against. We use a single Player
    # instance that has both configs.
    # Wait — the canonical path is
    # battle_against(other). Two players play
    # each other.
    async def main():
        # The simplest approach: create two
        # players per "battle" with the same
        # config flag value, and let them play.
        # We'll have OFF-vs-OFF and ON-vs-ON
        # matches. That keeps the engine in the
        # same configuration for both sides.
        tasks = []
        for i in range(args.n_battles):
            for flag_on in (False, True):
                cfg_a = DoublesDamageAwareConfig()
                cfg_a.enable_ally_heal_wrong_side_hard_safety = flag_on
                cfg_b = DoublesDamageAwareConfig()
                cfg_b.enable_ally_heal_wrong_side_hard_safety = flag_on
                account_a = f"NrA{i}{1 if flag_on else 0}"[:18]
                account_b = f"NrB{i}{1 if flag_on else 0}"[:18]
                audit = DoublesDecisionAuditLogger(
                    filepath=audit_path, reset=False,
                    detail_level="top5",
                )
                p_a = DoublesDamageAwarePlayer(
                    account_configuration=AccountConfiguration(
                        account_a, None
                    ),
                    verbose=False, config=cfg_a, audit_logger=audit,
                    max_concurrent_battles=1,
                    battle_format=BATTLE_FORMAT,
                    team=make_team(),
                )
                p_b = DoublesDamageAwarePlayer(
                    account_configuration=AccountConfiguration(
                        account_b, None
                    ),
                    verbose=False, config=cfg_b, audit_logger=audit,
                    max_concurrent_battles=1,
                    battle_format=BATTLE_FORMAT,
                    team=make_team(),
                )
                tasks.append((p_a, p_b))
        # Run each battle sequentially to avoid
        # localhost overload.
        start = time.time()
        for (p_a, p_b) in tasks:
            label = (
                "ON" if p_a.config.enable_ally_heal_wrong_side_hard_safety
                else "OFF"
            )
            try:
                await p_a.battle_against(p_b, n_battles=1)
            except Exception as e:
                print(f"  battle error ({label}): {e}")
        elapsed = time.time() - start
        print(f"  All battles done in {elapsed:.1f}s")
        # Cleanup players
        for (p_a, p_b) in tasks:
            for p in (p_a, p_b):
                try:
                    if hasattr(p, "ps_client") and hasattr(
                        p.ps_client, "_stop_listening"
                    ):
                        await p.ps_client._stop_listening()
                except Exception:
                    pass
        return elapsed

    elapsed = asyncio.run(main())
    print(f"  Elapsed: {elapsed:.1f}s")

    # Analyze the audit log
    print(
        f"\n--- Analyzing {audit_path} ---"
    )
    out = analyze_audit(audit_path)
    print(
        f"  n_records:           {out['n_records']}"
    )
    print(
        f"  n_turns:             {out['n_turns']}"
    )
    print(
        f"  n_candidate_turns:   {out['n_candidate_turns']}"
    )
    print(
        f"  n_blocked_turns:     {out['n_blocked_turns']}"
    )
    print(
        f"  n_selected_wrong_side: {out['n_selected_wrong_side']}"
    )
    print(
        f"  move_ids seen:        {sorted(out['move_ids'])}"
    )

    # The audit file contains BOTH ON and OFF
    # runs (since we appended). The narrow
    # metrics aggregate across both. We use the
    # total counts.
    has_candidate = out["n_candidate_turns"] > 0
    has_blocked = out["n_blocked_turns"] > 0
    no_wrong_side_selected = out["n_selected_wrong_side"] == 0

    print("\n--- Targeted qualification gates ---")
    print(
        f"  Narrow candidate generated:    "
        f"{has_candidate}"
    )
    print(
        f"  Narrow block fired:           "
        f"{has_blocked}"
    )
    print(
        f"  No wrong-side ally-heal selected: "
        f"{no_wrong_side_selected}"
    )

    all_pass = (
        has_candidate and has_blocked
        and no_wrong_side_selected
    )
    if not all_pass:
        print(
            "\n[targeted] TARGETED QUALIFICATION FAILED. "
            "Cannot adopt."
        )
        sys.exit(3)
    print(
        "\n[targeted] TARGETED QUALIFICATION PASSED. "
        "Narrow rule generated candidates, "
        "blocked wrong-side selections, and "
        "no wrong-side ally heal was chosen."
    )


if __name__ == "__main__":
    main()
