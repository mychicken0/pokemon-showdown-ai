#!/usr/bin/env python3
"""Phase 6.3.4 — Adopted Default Verification

Verifies the real adopted DoublesDamageAwareConfig defaults by running
benchmarks WITHOUT overriding any ability safety flags.
"""
import asyncio
import csv
import json
import os
import random

from poke_env import AccountConfiguration
from bot_doubles_damage_aware import (
    DoublesDamageAwareConfig,
    DoublesDamageAwarePlayer,
)
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15
CSV_PATH = "logs/doubles_adopted_ability_safety_verification.csv"


def count_audit_metrics(log_path):
    """Count all required metrics from a JSONL audit log."""
    metrics = {
        "protect_cnt": 0,
        "spread_cnt": 0,
        "focus_fire_cnt": 0,
        "ground_into_levitate": 0,
        "direct_absorb_immune_move_selected": 0,
        "direct_absorb_hard_block_avoided": 0,
        "direct_absorb_only_legal_action": 0,
        "redirected_absorb_selected": 0,
        "productive_partial_absorb_spread": 0,
        "zero_eff_cnt": 0,
        "all_imm_cnt": 0,
    }

    if not os.path.exists(log_path):
        return metrics

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                for turn in battle.get("audit_turns", []):
                    if turn.get("focus_fire_triggered"):
                        metrics["focus_fire_cnt"] += 1

                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue

                        action_types = slot.get("action_types", {})

                        if action_types.get("protect"):
                            metrics["protect_cnt"] += 1
                        if action_types.get("spread"):
                            metrics["spread_cnt"] += 1
                        if slot.get("zero_effectiveness_move_selected"):
                            metrics["zero_eff_cnt"] += 1
                        if slot.get("all_targets_immune_spread_selected"):
                            metrics["all_imm_cnt"] += 1
                        if slot.get("ground_into_levitate_selected"):
                            metrics["ground_into_levitate"] += 1
                        if slot.get("direct_absorb_immune_move_selected"):
                            metrics["direct_absorb_immune_move_selected"] += 1
                        if slot.get("direct_absorb_hard_block_avoided"):
                            metrics["direct_absorb_hard_block_avoided"] += 1
                        if slot.get("direct_absorb_only_legal_action"):
                            metrics["direct_absorb_only_legal_action"] += 1

                        is_absorb_selected = bool(slot.get("absorb_immune_move_selected"))
                        is_redirected = bool(slot.get("absorb_via_redirection"))
                        is_prod_spread = bool(slot.get("productive_partial_absorb_spread"))

                        if is_absorb_selected and is_redirected:
                            metrics["redirected_absorb_selected"] += 1
                        if is_absorb_selected and is_prod_spread:
                            metrics["productive_partial_absorb_spread"] += 1
            except Exception:
                continue

    return metrics


async def run_matchup(name, config, opp_class, n_battles, log_path):
    suffix = random.randint(10000, 99999)
    label = f"{name[:12]}_{suffix}"
    bot_name = f"Ver_{label}"[:18]
    opp_name = f"Opp_{label}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5",
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT,
    )

    if opp_class == DoublesBasicAwarePlayer:
        opponent = DoublesBasicAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            max_concurrent_battles=MAX_CONCURRENT,
        )
    elif opp_class == DoublesSafeRandomPlayer:
        opponent = DoublesSafeRandomPlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            max_concurrent_battles=MAX_CONCURRENT,
        )
    else:
        raise ValueError(f"Unknown opponent class: {opp_class}")

    print(f"\n---> {name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    planned = n_battles
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    unfinished = planned - finished
    ties_or_unknown = finished - wins - losses
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    crashes = exceptions = timeouts = 0
    for b in player.battles.values():
        if b.finished:
            if getattr(b, "crashed", False):
                crashes += 1
            if getattr(b, "exception", False):
                exceptions += 1
            if getattr(b, "timed_out", False):
                timeouts += 1

    m = count_audit_metrics(log_path)

    print(f"  Finished: {finished}/{planned} | Wins: {wins} | Losses: {losses} | Ties: {ties_or_unknown}")
    print(f"  Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Crashes: {crashes} | Exceptions: {exceptions} | Timeouts: {timeouts}")
    print(f"  Protect: {m['protect_cnt']} | Spread: {m['spread_cnt']} | Focus-fire: {m['focus_fire_cnt']}")
    print(f"  Ground->Levitate: {m['ground_into_levitate']}")
    print(f"  Direct Absorb Immune Selected: {m['direct_absorb_immune_move_selected']}")
    print(f"  Direct Absorb Hard Block Avoided: {m['direct_absorb_hard_block_avoided']}")
    print(f"  Direct Absorb Only-Legal: {m['direct_absorb_only_legal_action']}")
    print(f"  Redirected Absorb: {m['redirected_absorb_selected']}")
    print(f"  Productive Partial Absorb Spread: {m['productive_partial_absorb_spread']}")
    print(f"  Zero-Effectiveness: {m['zero_eff_cnt']} | All-Target Immune: {m['all_imm_cnt']}")

    return {
        "matchup": name,
        "planned_battles": planned,
        "finished_battles": finished,
        "unfinished_battles": unfinished,
        "wins": wins,
        "losses": losses,
        "ties_or_unknown": ties_or_unknown,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "crashes": crashes,
        "exceptions": exceptions,
        "timeouts": timeouts,
        **m,
    }


async def main():
    os.makedirs("logs", exist_ok=True)

    # Instantiate the REAL adopted default — no overrides
    config = DoublesDamageAwareConfig()

    print("=" * 70)
    print("  Phase 6.3.4 — Adopted Default Verification")
    print("  Using DoublesDamageAwareConfig() with NO overrides")
    print("=" * 70)

    # --- Run 1: vs DoublesBasicAwarePlayer (500 battles) ---
    row1 = await run_matchup(
        name="Adopted Default vs Basic",
        config=config,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=500,
        log_path="logs/doubles_adopted_ability_safety_vs_basic.jsonl",
    )

    # --- Run 2: vs DoublesSafeRandomPlayer (100 battles) ---
    row2 = await run_matchup(
        name="Adopted Default vs SafeRandom",
        config=config,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=100,
        log_path="logs/doubles_adopted_ability_safety_vs_safe_random.jsonl",
    )

    # --- Write CSV ---
    fieldnames = [
        "matchup", "planned_battles", "finished_battles", "unfinished_battles",
        "wins", "losses", "ties_or_unknown", "win_rate", "avg_turns",
        "crashes", "exceptions", "timeouts",
        "protect_cnt", "spread_cnt", "focus_fire_cnt",
        "ground_into_levitate",
        "direct_absorb_immune_move_selected",
        "direct_absorb_hard_block_avoided",
        "direct_absorb_only_legal_action",
        "redirected_absorb_selected",
        "productive_partial_absorb_spread",
        "zero_eff_cnt", "all_imm_cnt",
    ]

    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row1)
        writer.writerow(row2)

    print(f"\nCSV written to {CSV_PATH}")

    # --- Acceptance Checks ---
    print("\n" + "=" * 70)
    print("  ACCEPTANCE CHECKS")
    print("=" * 70)

    checks = []

    def check(label, condition):
        status = "PASS" if condition else "FAIL"
        checks.append((label, condition))
        print(f"  [{status}] {label}")
        return condition

    all_pass = True

    # Stability
    all_pass &= check(
        "All 600 battles finished",
        row1["finished_battles"] == 500 and row2["finished_battles"] == 100,
    )
    all_pass &= check(
        "No unfinished battles",
        row1["unfinished_battles"] == 0 and row2["unfinished_battles"] == 0,
    )
    all_pass &= check(
        "No crashes",
        row1["crashes"] == 0 and row2["crashes"] == 0,
    )
    all_pass &= check(
        "No exceptions",
        row1["exceptions"] == 0 and row2["exceptions"] == 0,
    )
    all_pass &= check(
        "No timeouts",
        row1["timeouts"] == 0 and row2["timeouts"] == 0,
    )

    # Safety
    all_pass &= check(
        f"Ground into known Levitate near zero (Basic={row1['ground_into_levitate']}, SafeRandom={row2['ground_into_levitate']})",
        row1["ground_into_levitate"] <= 5 and row2["ground_into_levitate"] <= 2,
    )

    # Direct absorb: immune selections zero (except only-legal)
    direct_immune_basic = row1["direct_absorb_immune_move_selected"]
    direct_immune_random = row2["direct_absorb_immune_move_selected"]
    direct_only_legal_basic = row1["direct_absorb_only_legal_action"]
    direct_only_legal_random = row2["direct_absorb_only_legal_action"]
    non_only_legal_basic = direct_immune_basic - direct_only_legal_basic
    non_only_legal_random = direct_immune_random - direct_only_legal_random
    all_pass &= check(
        "Direct known-absorb immune selections zero except only-legal cases",
        non_only_legal_basic == 0 and non_only_legal_random == 0,
    )

    # Win rate
    safe_random_wr = float(row2["win_rate"])
    all_pass &= check(
        f"SafeRandom win rate >= 95% (got {safe_random_wr:.2f}%)",
        safe_random_wr >= 95.0,
    )

    # Behavioral: spread and focus-fire remain active
    all_pass &= check(
        "Spread usage active vs Basic (>0)",
        row1["spread_cnt"] > 0,
    )
    all_pass &= check(
        "Focus-fire usage active vs Basic (>0)",
        row1["focus_fire_cnt"] > 0,
    )

    # Redirected and productive spread remain outside direct safety
    all_pass &= check(
        "Redirected absorb selections recorded (>=0, no crash)",
        row1["redirected_absorb_selected"] >= 0,
    )
    all_pass &= check(
        "Productive partial absorb spreads recorded (>=0, no crash)",
        row1["productive_partial_absorb_spread"] >= 0,
    )

    # Defaults unchanged verification
    print("\n" + "=" * 70)
    print("  DEFAULT VERIFICATION")
    print("=" * 70)
    all_pass &= check("enable_ability_hard_safety_only == True", config.enable_ability_hard_safety_only is True)
    all_pass &= check("ability_hard_safety_direct_absorb_only == True", config.ability_hard_safety_direct_absorb_only is True)
    all_pass &= check("ability_hard_safety_avoid_absorb == False", config.ability_hard_safety_avoid_absorb is False)
    all_pass &= check("ability_hard_safety_avoid_redirection == False", config.ability_hard_safety_avoid_redirection is False)
    all_pass &= check("ability_hard_safety_ally_spread_safety == False", config.ability_hard_safety_ally_spread_safety is False)
    all_pass &= check("enable_ability_awareness == False", config.enable_ability_awareness is False)
    all_pass &= check("enable_meta_opponent_modeling == False", config.enable_meta_opponent_modeling is False)
    all_pass &= check("enable_random_set_opponent_modeling == False", config.enable_random_set_opponent_modeling is False)
    all_pass &= check("enable_threat_tiebreaker == False", config.enable_threat_tiebreaker is False)

    print("\n" + "=" * 70)
    if all_pass:
        print("  ALL ACCEPTANCE CHECKS PASSED")
    else:
        print("  SOME ACCEPTANCE CHECKS FAILED — review above")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
