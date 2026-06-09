#!/usr/bin/env python3
import asyncio
import csv
import json
import os
import random
import sys
from poke_env import AccountConfiguration
from bot_doubles_damage_aware import DoublesDamageAwarePlayer, DoublesDamageAwareConfig
from bot_doubles_basic_aware import DoublesBasicAwarePlayer
from bot_doubles_safe_random import DoublesSafeRandomPlayer
from doubles_decision_audit_logger import DoublesDecisionAuditLogger

MAX_CONCURRENT = 15
SUMMARY_CSV_PATH = "logs/doubles_absorb_error_audit_run2_summary.csv"

def count_audit_absorb_metrics(log_path):
    metrics = {
        "total_battles": 0,
        "wins": 0,
        "losses": 0,
        "absorb_selected_action_count": 0,
        "direct_absorb_selected_action_count": 0,
        "redirected_absorb_selected_action_count": 0,
        "absorb_avoidable_action_count": 0,
        "direct_avoidable_absorb_action_count": 0,
        "redirected_avoidable_absorb_action_count": 0,
        "forced_no_useful_scored_alt_action_count": 0,
        "avoidable_safe_damage_alt_action_count": 0,
        "productive_partial_spread_action_count": 0,
        "other_useful_scored_alt_action_count": 0,
        "unclassified_action_count": 0,
        "absorb_streak_gte_2_count": 0,
        "absorb_max_streak": 0,
        "battles_with_absorb_selected_win": 0,
        "battles_with_absorb_selected_loss": 0,
        "battles_with_absorb_avoidable_win": 0,
        "battles_with_absorb_avoidable_loss": 0,
        "battles_with_forced_win": 0,
        "battles_with_forced_loss": 0,
        "battles_with_productive_spread_win": 0,
        "battles_with_productive_spread_loss": 0
    }

    if not os.path.exists(log_path):
        return metrics

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                metrics["total_battles"] += 1
                won = bool(battle.get("won", False))
                if won:
                    metrics["wins"] += 1
                else:
                    metrics["losses"] += 1

                battle_has_selected = False
                battle_has_avoidable = False
                battle_has_forced = False
                battle_has_productive = False

                for turn in battle.get("audit_turns", []):
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue

                        is_selected = bool(slot.get("absorb_immune_move_selected"))
                        is_redirected = bool(slot.get("absorb_via_redirection", False))
                        is_forced = bool(slot.get("absorb_selection_forced"))
                        is_avoidable = bool(slot.get("avoidable_absorb_error"))
                        is_productive = bool(slot.get("productive_partial_absorb_spread"))
                        streak = int(slot.get("absorb_selected_streak", 0))

                        if is_selected:
                            metrics["absorb_selected_action_count"] += 1
                            battle_has_selected = True
                            if is_redirected:
                                metrics["redirected_absorb_selected_action_count"] += 1
                            else:
                                metrics["direct_absorb_selected_action_count"] += 1

                            # Exhaustive classification
                            if is_productive:
                                metrics["productive_partial_spread_action_count"] += 1
                            elif is_avoidable:
                                metrics["avoidable_safe_damage_alt_action_count"] += 1
                            elif is_forced:
                                metrics["forced_no_useful_scored_alt_action_count"] += 1
                            elif not slot.get("absorb_safe_alternative_available") and not is_forced:
                                metrics["other_useful_scored_alt_action_count"] += 1
                            else:
                                metrics["unclassified_action_count"] += 1

                        if is_forced:
                            battle_has_forced = True
                        if is_avoidable:
                            metrics["absorb_avoidable_action_count"] += 1
                            battle_has_avoidable = True
                            if is_redirected:
                                metrics["redirected_avoidable_absorb_action_count"] += 1
                            else:
                                metrics["direct_avoidable_absorb_action_count"] += 1
                        if is_productive:
                            battle_has_productive = True

                        if streak >= 2:
                            metrics["absorb_streak_gte_2_count"] += 1
                        if streak > metrics["absorb_max_streak"]:
                            metrics["absorb_max_streak"] = streak

                if battle_has_selected:
                    if won:
                        metrics["battles_with_absorb_selected_win"] += 1
                    else:
                        metrics["battles_with_absorb_selected_loss"] += 1

                if battle_has_avoidable:
                    if won:
                        metrics["battles_with_absorb_avoidable_win"] += 1
                    else:
                        metrics["battles_with_absorb_avoidable_loss"] += 1

                if battle_has_forced:
                    if won:
                        metrics["battles_with_forced_win"] += 1
                    else:
                        metrics["battles_with_forced_loss"] += 1

                if battle_has_productive:
                    if won:
                        metrics["battles_with_productive_spread_win"] += 1
                    else:
                        metrics["battles_with_productive_spread_loss"] += 1

            except Exception:
                continue

    return metrics

async def run_matchup(name, config, opp_class, n_battles, log_path, label):
    suffix = random.randint(1000, 9999)
    bot_name = f"Audit_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5"
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT
    )

    if opp_class == DoublesBasicAwarePlayer:
        opponent = DoublesBasicAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            max_concurrent_battles=MAX_CONCURRENT
        )
    elif opp_class == DoublesSafeRandomPlayer:
        opponent = DoublesSafeRandomPlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            max_concurrent_battles=MAX_CONCURRENT
        )
    else:
        raise ValueError(f"Unknown opponent class: {opp_class}")

    print(f"\n---> Starting Audit Run {label}: {name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    m = count_audit_absorb_metrics(log_path)

    print(f"Audit Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Selected absorb moves: {m['absorb_selected_action_count']} | Forced: {m['forced_no_useful_scored_alt_action_count']} | Avoidable: {m['absorb_avoidable_action_count']} | Productive Spread: {m['productive_partial_spread_action_count']}")
    print(f"  Max Streak: {m['absorb_max_streak']} | Streak >= 2: {m['absorb_streak_gte_2_count']}")

    return {
        "matchup": name,
        "total_battles": finished,
        "wins": wins,
        "losses": losses,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        **m
    }

def summarize_existing_logs():
    os.makedirs("logs", exist_ok=True)
    runs_data = []

    targets = [
        {
            "name": "Adopted Default vs Basic",
            "log_path": "logs/doubles_absorb_error_audit_run2_vs_basic.jsonl",
            "label": "Basic"
        },
        {
            "name": "Adopted Default vs SafeRandom",
            "log_path": "logs/doubles_absorb_error_audit_run2_vs_safe_random.jsonl",
            "label": "SafeRandom"
        }
    ]

    for t in targets:
        log_path = t["log_path"]
        if not os.path.exists(log_path):
            print(f"Error: {log_path} does not exist.")
            continue
        
        total_turns_sum = 0
        with open(log_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    battle = json.loads(line)
                    turns = battle.get("audit_turns", [])
                    if turns:
                        total_turns_sum += turns[-1].get("turn", 0)
                except Exception:
                    continue

        m = count_audit_absorb_metrics(log_path)
        wins = m["wins"]
        losses = m["losses"]
        finished = m["total_battles"]
        win_rate = (wins / finished) * 100 if finished > 0 else 0.0
        avg_turns = (total_turns_sum / finished) if finished > 0 else 0.0

        print(f"\n---> Summarized Existing Audit Run {t['label']}: {t['name']} ({finished} battles)...")
        print(f"Audit Run {t['label']} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
        print(f"  Selected absorb moves: {m['absorb_selected_action_count']} | Forced: {m['forced_no_useful_scored_alt_action_count']} | Avoidable: {m['absorb_avoidable_action_count']} | Productive Spread: {m['productive_partial_spread_action_count']} | Other Useful Alt: {m['other_useful_scored_alt_action_count']}")
        print(f"  Max Streak: {m['absorb_max_streak']} | Streak >= 2: {m['absorb_streak_gte_2_count']}")

        runs_data.append({
            "matchup": t["name"],
            "total_battles": finished,
            "wins": wins,
            "losses": losses,
            "win_rate": f"{win_rate:.2f}",
            "avg_turns": f"{avg_turns:.2f}",
            **m
        })

    fieldnames = [
        "matchup", "total_battles", "wins", "losses", "win_rate", "avg_turns",
        "absorb_selected_action_count",
        "absorb_avoidable_action_count",
        "forced_no_useful_scored_alt_action_count",
        "productive_partial_spread_action_count",
        "other_useful_scored_alt_action_count",
        "unclassified_action_count",
        "direct_absorb_selected_action_count",
        "redirected_absorb_selected_action_count",
        "direct_avoidable_absorb_action_count",
        "redirected_avoidable_absorb_action_count",
        "battles_with_absorb_selected_win",
        "battles_with_absorb_selected_loss",
        "battles_with_absorb_avoidable_win",
        "battles_with_absorb_avoidable_loss",
        "battles_with_forced_win",
        "battles_with_forced_loss",
        "battles_with_productive_spread_win",
        "battles_with_productive_spread_loss"
    ]
    with open(SUMMARY_CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in runs_data:
            filtered_row = {k: v for k, v in row.items() if k in fieldnames}
            writer.writerow(filtered_row)

    print(f"\nAbsorb Error Audit finished. Summary written to: {SUMMARY_CSV_PATH}")

async def main():
    os.makedirs("logs", exist_ok=True)

    config_default = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        enable_order_aware_overkill=False,
        enable_ability_hard_safety_only=True,
        ability_hard_safety_avoid_absorb=False,
        ability_hard_safety_avoid_redirection=False,
        ability_hard_safety_ally_spread_safety=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    runs_data = []

    r1 = await run_matchup(
        name="Adopted Default vs Basic",
        config=config_default,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=300,
        log_path="logs/doubles_absorb_error_audit_run2_vs_basic.jsonl",
        label="Basic"
    )
    runs_data.append(r1)

    r2 = await run_matchup(
        name="Adopted Default vs SafeRandom",
        config=config_default,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=100,
        log_path="logs/doubles_absorb_error_audit_run2_vs_safe_random.jsonl",
        label="SafeRandom"
    )
    runs_data.append(r2)

    fieldnames = [
        "matchup", "total_battles", "wins", "losses", "win_rate", "avg_turns",
        "absorb_selected_action_count",
        "absorb_avoidable_action_count",
        "forced_no_useful_scored_alt_action_count",
        "productive_partial_spread_action_count",
        "other_useful_scored_alt_action_count",
        "unclassified_action_count",
        "direct_absorb_selected_action_count",
        "redirected_absorb_selected_action_count",
        "direct_avoidable_absorb_action_count",
        "redirected_avoidable_absorb_action_count",
        "battles_with_absorb_selected_win",
        "battles_with_absorb_selected_loss",
        "battles_with_absorb_avoidable_win",
        "battles_with_absorb_avoidable_loss",
        "battles_with_forced_win",
        "battles_with_forced_loss",
        "battles_with_productive_spread_win",
        "battles_with_productive_spread_loss"
    ]
    with open(SUMMARY_CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in runs_data:
            filtered_row = {k: v for k, v in row.items() if k in fieldnames}
            writer.writerow(filtered_row)

    print(f"\nAbsorb Error Audit finished. Summary written to: {SUMMARY_CSV_PATH}")

if __name__ == "__main__":
    if "--summarize-existing" in sys.argv:
        summarize_existing_logs()
    else:
        asyncio.run(main())
