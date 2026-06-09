#!/usr/bin/env python3
"""Phase 6.4.2 Benchmark - Revealed-Move One-Ply Defensive Switching.

Uses real DoublesDamageAwarePlayer instances with proper config and audit logging.
Run with: venv/bin/python bot_doubles_revealed_move_switch_interception_benchmark.py
"""

import asyncio
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from doubles_decision_audit_logger import DoublesDecisionAuditLogger
from poke_env import AccountConfiguration


async def run_matchup(name, primary_config, opp_class, opp_config, n_battles, log_path):
    """Run a single matchup using real DoublesDamageAwarePlayer instances."""
    if opp_class == "basic":
        from bot_doubles_basic_aware import DoublesBasicAwarePlayer
        OpponentClass = DoublesBasicAwarePlayer
    elif opp_class == "safe_random":
        from bot_doubles_safe_random import DoublesSafeRandomPlayer
        OpponentClass = DoublesSafeRandomPlayer
    elif opp_class == "mirror":
        OpponentClass = DoublesDamageAwarePlayer
    else:
        raise ValueError(f"Unknown opponent class: {opp_class}")

    suffix = int(time.time() * 1000) % 100000
    bot_name = f"P642a_{name.replace(' ', '_')[:6]}_{suffix}"[:18]
    opp_name = f"Opp_{name.replace(' ', '_')[:6]}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5",
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=primary_config,
        audit_logger=audit_logger,
        max_concurrent_battles=8,
    )

    if opp_class == "mirror":
        opponent = OpponentClass(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=opp_config,
            max_concurrent_battles=8,
        )
    else:
        opponent = OpponentClass(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            max_concurrent_battles=8,
        )

    print(f"\n---> {name}: {n_battles} battles")
    start_time = time.time()

    await player.battle_against(opponent, n_battles=n_battles)

    elapsed = time.time() - start_time
    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles if hasattr(opponent, 'n_won_battles') else 0
    ties = finished - wins - losses
    win_rate = (wins / finished * 100) if finished > 0 else 0.0

    turns = []
    for b in player.battles.values():
        if b.finished:
            turns.append(b.turn)
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    # Count audit metrics from JSONL
    m = _count_audit_metrics(log_path)

    print(f"  Finished: {finished}/{n_battles} | W: {wins} L: {losses} T: {ties} | WR: {win_rate:.1f}% | Avg Turns: {avg_turns:.1f}")
    print(f"  Predictions available: {m['predictions_available']} | Selected: {m['interceptions_selected']}")
    print(f"  Correct: {m['correct_predictions']} | Wrong: {m['wrong_predictions']} | Unresolved: {m['unresolved_predictions']}")
    print(f"  Survived: {m['survived_after_switch']} | Fainted: {m['candidate_fainted']}")
    print(f"  KO blocked: {m['ko_blocked']} | HV blocked: {m['hv_blocked']} | Worse-other: {m['worse_other']}")
    print(f"  Our type-immune: {m['our_type_immune']} | Opp type-immune: {m['opp_type_immune']}")
    print(f"  Protect: {m['protect']} | Spread: {m['spread']} | Focus-fire: {m['focus_fire']}")

    return {
        "name": name,
        "planned": n_battles,
        "finished": finished,
        "unfinished": n_battles - finished,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "elapsed": f"{elapsed:.1f}",
        "crashes": 0,
        "exceptions": 0,
        "timeouts": 0,
        **m,
    }


def _count_audit_metrics(log_path):
    """Count Phase 6.4.2 metrics from JSONL audit log."""
    m = {
        "predictions_available": 0,
        "interceptions_selected": 0,
        "selections_changed": 0,
        "correct_predictions": 0,
        "wrong_predictions": 0,
        "unresolved_predictions": 0,
        "survived_after_switch": 0,
        "candidate_fainted": 0,
        "ko_blocked": 0,
        "hv_blocked": 0,
        "worse_other": 0,
        "our_type_immune": 0,
        "opp_type_immune": 0,
        "electric_ground": 0,
        "protect": 0,
        "spread": 0,
        "focus_fire": 0,
    }

    if not os.path.exists(log_path):
        return m

    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                for turn in record.get("audit_turns", []):
                    # Per-slot metrics
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue

                        act_types = slot.get("action_types", {})
                        if act_types.get("protect"):
                            m["protect"] += 1
                        if act_types.get("spread"):
                            m["spread"] += 1

                        if slot.get("revealed_switch_prediction_available"):
                            m["predictions_available"] += 1
                        if slot.get("revealed_switch_interception_selected"):
                            m["interceptions_selected"] += 1
                        if slot.get("revealed_switch_selection_changed"):
                            m["selections_changed"] += 1
                        if slot.get("revealed_switch_prediction_correct"):
                            m["correct_predictions"] += 1
                        if slot.get("revealed_switch_prediction_wrong"):
                            m["wrong_predictions"] += 1
                        # unresolved = prediction_available but neither correct nor wrong
                        if (slot.get("revealed_switch_prediction_available")
                                and not slot.get("revealed_switch_prediction_correct")
                                and not slot.get("revealed_switch_prediction_wrong")):
                            m["unresolved_predictions"] += 1

                        survived = slot.get("revealed_switch_post_turn_survived")
                        if survived is True:
                            m["survived_after_switch"] += 1
                        elif survived is False:
                            m["candidate_fainted"] += 1

                        if slot.get("revealed_switch_blocked_by_ko_action"):
                            m["ko_blocked"] += 1
                        if slot.get("revealed_switch_blocked_by_high_value_action"):
                            m["hv_blocked"] += 1
                        if slot.get("revealed_switch_rejected_worse_other_threat"):
                            m["worse_other"] += 1
                        if slot.get("our_type_immune_move_selected"):
                            m["our_type_immune"] += 1

                    # Opponent metrics
                    opp = turn.get("opp_actions", {})
                    if opp.get("opponent_type_immune_move_selected"):
                        m["opp_type_immune"] += 1

                    # Focus fire
                    if turn.get("focus_fire_triggered"):
                        m["focus_fire"] += 1

            except Exception:
                continue

    return m


async def main():
    print("=" * 70)
    print("Phase 6.4.2a Benchmark - Revealed-Move Switch Interception")
    print("Using real DoublesDamageAwarePlayer with proper config and audit")
    print("=" * 70)

    os.makedirs("logs", exist_ok=True)

    config_off = DoublesDamageAwareConfig(
        enable_revealed_move_switch_interception=False,
    )
    config_on = DoublesDamageAwareConfig(
        enable_revealed_move_switch_interception=True,
    )

    results = []

    # Run 1: Off vs Basic (500)
    r1 = await run_matchup(
        "Off vs Basic", config_off, "basic", None, 500,
        "logs/phase642a_off_vs_basic.jsonl"
    )
    results.append(r1)

    # Run 2: On vs Basic (500)
    r2 = await run_matchup(
        "On vs Basic", config_on, "basic", None, 500,
        "logs/phase642a_on_vs_basic.jsonl"
    )
    results.append(r2)

    # Run 3: On vs Off (500)
    r3 = await run_matchup(
        "On vs Off", config_on, "mirror", config_off, 500,
        "logs/phase642a_on_vs_off.jsonl"
    )
    results.append(r3)

    # Run 4: On vs SafeRandom (100)
    r4 = await run_matchup(
        "On vs SafeRandom", config_on, "safe_random", None, 100,
        "logs/phase642a_on_vs_saferandom.jsonl"
    )
    results.append(r4)

    # Write CSV
    csv_path = "logs/phase642a_benchmark.csv"
    fieldnames = [
        "name", "planned", "finished", "unfinished", "wins", "losses", "ties",
        "win_rate", "avg_turns", "elapsed", "crashes", "exceptions", "timeouts",
        "predictions_available", "interceptions_selected", "selections_changed",
        "correct_predictions", "wrong_predictions", "unresolved_predictions",
        "survived_after_switch", "candidate_fainted",
        "ko_blocked", "hv_blocked", "worse_other",
        "our_type_immune", "opp_type_immune", "electric_ground",
        "protect", "spread", "focus_fire",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        wr = float(r["win_rate"])
        print(f"  {r['name']:20s}: {r['wins']:3d}/{r['planned']} ({wr:5.1f}%) | "
              f"pred={r['predictions_available']:4d} sel={r['interceptions_selected']:3d} "
              f"correct={r['correct_predictions']:3d} wrong={r['wrong_predictions']:3d} "
              f"unres={r['unresolved_predictions']:3d}")

    # Precision
    for r in results:
        total_pred = r["correct_predictions"] + r["wrong_predictions"]
        if total_pred > 0:
            prec = r["correct_predictions"] / total_pred * 100
            print(f"  {r['name']:20s}: prediction precision = {prec:.1f}% ({r['correct_predictions']}/{total_pred})")
        else:
            print(f"  {r['name']:20s}: prediction precision = N/A (no predictions)")

    print(f"\nCSV saved to {csv_path}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
