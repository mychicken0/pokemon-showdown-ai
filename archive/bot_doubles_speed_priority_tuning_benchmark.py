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

MAX_CONCURRENT = 10
CSV_PATH = "logs/doubles_speed_priority_tuning_benchmark.csv"
N_BATTLES_TUNE = 100
N_BATTLES_SAFETY = 100

def count_speed_priority_metrics(log_path):
    metrics = {
        "protect_cnt": 0,
        "switch_cnt": 0,
        "detected_threat": 0,
        "true_unanswered": 0,
        "productive_attack": 0,
        "false_positive": 0,
        "bad_protect_refined": 0,
        "overkill_cnt": 0
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
                    if turn.get("order_aware_overkill_penalty_applied"):
                        metrics["overkill_cnt"] += 1
                        
                    slot_0 = turn.get("slot_0", {})
                    slot_1 = turn.get("slot_1", {})
                    
                    for idx, (slot, other) in enumerate([(slot_0, slot_1), (slot_1, slot_0)]):
                        action_types = slot.get("action_types", {})
                        if action_types.get("protect"):
                            metrics["protect_cnt"] += 1
                        if action_types.get("switch"):
                            metrics["switch_cnt"] += 1
                            
                        if not slot.get("outcome_known"):
                            continue
                            
                        # Pattern 21: detected_speed_priority_threat
                        if slot.get("speed_priority_threatened"):
                            metrics["detected_threat"] += 1
                            
                            # Pattern 22: true_unanswered_speed_priority_threat
                            is_protect = action_types.get("protect")
                            is_switch = action_types.get("switch")
                            if not is_protect and not is_switch:
                                not_unanswered = (
                                    slot.get("fainted_before_moving") == False or
                                    slot.get("actual_ko") == True or
                                    (action_types.get("spread") and slot.get("actual_damage") is not None and slot.get("actual_damage") >= 0.20) or
                                    slot.get("protect_like_available") == False or
                                    slot.get("switch_available") == False or
                                    slot.get("only_conditional_priority") == True or
                                    slot.get("was_targeted") == False or
                                    slot.get("active_moved_before_threat") == True
                                )
                                if not not_unanswered:
                                    metrics["true_unanswered"] += 1
                                    
                                # Pattern 23: productive_attack_under_threat
                                is_attack = slot.get("action") and "pass" not in slot.get("action", "")
                                if is_attack:
                                    is_productive = (
                                        slot.get("actual_ko") == True or
                                        (action_types.get("spread") and slot.get("actual_damage") is not None and slot.get("actual_damage") > 0.0) or
                                        (slot.get("actual_damage") is not None and slot.get("actual_damage") >= 0.30)
                                    )
                                    if is_productive:
                                        metrics["productive_attack"] += 1
                                        
                            # Pattern 24: false_positive_speed_priority_threat
                            if slot.get("was_targeted") == False or slot.get("our_mon_fainted") == False:
                                metrics["false_positive"] += 1
                                
                        # Pattern 25: bad_speed_priority_protect_refined
                        if slot.get("protected_due_to_speed_priority") and action_types.get("protect"):
                            if slot.get("was_targeted") == False:
                                ally_did_good = (other.get("actual_ko") or (other.get("actual_damage") is not None and other["actual_damage"] >= 0.30))
                                if not ally_did_good:
                                    is_stalling = slot.get("stalling_field_condition", False)
                                    if not is_stalling:
                                        metrics["bad_protect_refined"] += 1
            except Exception:
                continue
    return metrics

async def run_matchup(name, config_on, opp_class, n_battles, log_path, label, opp_config=None):
    suffix = random.randint(1000, 9999)
    bot_name = f"TUNE_{label}_{suffix}"[:18]
    opp_name = f"Opp_{label}_{suffix}"[:18]

    audit_logger = DoublesDecisionAuditLogger(
        filepath=log_path,
        reset=True,
        detail_level="top5"
    )

    player = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(bot_name, None),
        verbose=False,
        config=config_on,
        audit_logger=audit_logger,
        max_concurrent_battles=MAX_CONCURRENT
    )

    if opp_class == DoublesDamageAwarePlayer:
        opp_log_path = log_path.replace(".jsonl", "_opp.jsonl")
        opp_audit_logger = DoublesDecisionAuditLogger(
            filepath=opp_log_path,
            reset=True,
            detail_level="top5"
        )
        opponent = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=opp_config,
            audit_logger=opp_audit_logger,
            max_concurrent_battles=MAX_CONCURRENT
        )
    elif opp_class == DoublesBasicAwarePlayer:
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

    print(f"\n---> Starting Run {label}: {name} ({n_battles} battles)...")
    await player.battle_against(opponent, n_battles=n_battles)

    finished = player.n_finished_battles
    wins = player.n_won_battles
    losses = opponent.n_won_battles
    win_rate = (wins / finished) * 100 if finished > 0 else 0.0

    turns = [b.turn for b in player.battles.values() if b.finished]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    m = count_speed_priority_metrics(log_path)

    print(f"Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Protect: {m['protect_cnt']} | Switch: {m['switch_cnt']} | Detected Threat: {m['detected_threat']}")
    print(f"  True Unanswered: {m['true_unanswered']} | Productive Attack: {m['productive_attack']}")
    print(f"  False Positive: {m['false_positive']} | Bad Protect Refined: {m['bad_protect_refined']}")

    return {
        "matchup": name,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        "protect_cnt": m["protect_cnt"],
        "switch_cnt": m["switch_cnt"],
        "detected_threat": m["detected_threat"],
        "true_unanswered": m["true_unanswered"],
        "productive_attack": m["productive_attack"],
        "false_positive": m["false_positive"],
        "bad_protect_refined": m["bad_protect_refined"],
        "overkill_cnt": m["overkill_cnt"]
    }

async def main():
    os.makedirs("logs", exist_ok=True)

    # Define Configurations for the Tuning Benchmarks
    
    # A) current_default_phase62 (scaled penalty disabled)
    config_a = DoublesDamageAwareConfig(
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        speed_priority_use_scaled_penalty=False,
        enable_order_aware_overkill=False
    )
    
    # B) scaled_confidence (scaled penalty enabled)
    config_b = DoublesDamageAwareConfig(
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        speed_priority_use_scaled_penalty=True,
        enable_order_aware_overkill=False
    )
    
    # C) reduced_protect_bonus
    config_c = DoublesDamageAwareConfig(
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        speed_priority_use_scaled_penalty=True,
        speed_priority_protect_bonus_low=20.0,
        speed_priority_protect_bonus_high=40.0,
        enable_order_aware_overkill=False
    )
    
    # D) reduced_attack_penalty
    config_d = DoublesDamageAwareConfig(
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        speed_priority_use_scaled_penalty=True,
        speed_priority_attack_penalty_low=15.0,
        speed_priority_attack_penalty_high=30.0,
        enable_order_aware_overkill=False
    )
    
    # E) conservative_conditional_priority
    config_e = DoublesDamageAwareConfig(
        enable_speed_priority_awareness=True,
        speed_priority_protect_only=False,
        speed_priority_use_scaled_penalty=True,
        speed_priority_conditional_priority_weight=0.30,
        enable_order_aware_overkill=False
    )

    runs_data = []

    # Run A: current_default_phase62 vs Basic
    res_a = await run_matchup(
        name="current_default_phase62 vs DoublesBasicAwarePlayer",
        config_on=config_a,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=N_BATTLES_TUNE,
        log_path="logs/doubles_tune_a.jsonl",
        label="A"
    )
    runs_data.append(res_a)

    # Run B: scaled_confidence vs Basic
    res_b = await run_matchup(
        name="scaled_confidence vs DoublesBasicAwarePlayer",
        config_on=config_b,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=N_BATTLES_TUNE,
        log_path="logs/doubles_tune_b.jsonl",
        label="B"
    )
    runs_data.append(res_b)

    # Run C: reduced_protect_bonus vs Basic
    res_c = await run_matchup(
        name="reduced_protect_bonus vs DoublesBasicAwarePlayer",
        config_on=config_c,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=N_BATTLES_TUNE,
        log_path="logs/doubles_tune_c.jsonl",
        label="C"
    )
    runs_data.append(res_c)

    # Run D: reduced_attack_penalty vs Basic
    res_d = await run_matchup(
        name="reduced_attack_penalty vs DoublesBasicAwarePlayer",
        config_on=config_d,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=N_BATTLES_TUNE,
        log_path="logs/doubles_tune_d.jsonl",
        label="D"
    )
    runs_data.append(res_d)

    # Run E: conservative_conditional_priority vs Basic
    res_e = await run_matchup(
        name="conservative_conditional_priority vs DoublesBasicAwarePlayer",
        config_on=config_e,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=N_BATTLES_TUNE,
        log_path="logs/doubles_tune_e.jsonl",
        label="E"
    )
    runs_data.append(res_e)

    # Analyze and Select Best Variant programmatically
    # Selection criteria:
    # 1. Win rate must not regress by more than 1.5% compared to Variant A.
    # 2. Prefer the lowest bad_protect_refined.
    # 3. If tied, select highest win rate.
    
    wr_a = float(res_a["win_rate"])
    candidates = [
        ("B", config_b, res_b),
        ("C", config_c, res_c),
        ("D", config_d, res_d),
        ("E", config_e, res_e)
    ]
    
    eligible = []
    for label, cfg, res in candidates:
        wr = float(res["win_rate"])
        if wr >= wr_a - 1.5:
            eligible.append((label, cfg, res))
            
    # If no candidate is eligible (all regressed too much), fallback to B (scaled confidence)
    if not eligible:
        print("\nWARNING: All tuned variants regressed more than 1.5% compared to A. Falling back to B.")
        best_label, best_config, best_res = "B", config_b, res_b
    else:
        # Sort eligible by bad_protect_refined (ascending), then win_rate (descending)
        eligible.sort(key=lambda x: (x[2]["bad_protect_refined"], -float(x[2]["win_rate"])))
        best_label, best_config, best_res = eligible[0]

    print(f"\n====== PROGRAMMATIC BEST TUNED VARIANT SELECTION ======")
    print(f"  Variant A (current_default_phase62) Win Rate: {wr_a}%")
    for l, c, r in candidates:
        print(f"  Variant {l} Win Rate: {r['win_rate']}% | Bad Protect Refined: {r['bad_protect_refined']}")
    print(f"  Selected Best Tuned Variant: {best_label}")
    print(f"========================================================\n")

    # Run F: best_tuned_variant vs current_default_phase62 (Variant A)
    res_f = await run_matchup(
        name=f"best_tuned_variant ({best_label}) vs current_default_phase62 (A)",
        config_on=best_config,
        opp_class=DoublesDamageAwarePlayer,
        n_battles=N_BATTLES_TUNE,
        log_path="logs/doubles_tune_f.jsonl",
        label="F",
        opp_config=config_a
    )
    runs_data.append(res_f)

    # Run G: best_tuned_variant vs DoublesSafeRandomPlayer
    res_g = await run_matchup(
        name=f"best_tuned_variant ({best_label}) vs DoublesSafeRandomPlayer",
        config_on=best_config,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=N_BATTLES_SAFETY,
        log_path="logs/doubles_tune_g.jsonl",
        label="G"
    )
    runs_data.append(res_g)

    # Save all results to CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "matchup", "win_rate", "avg_turns", "protect_cnt", "switch_cnt", "detected_threat",
            "true_unanswered", "productive_attack", "false_positive", "bad_protect_refined", "overkill_cnt"
        ])
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

    print(f"\nAll benchmark matchups finished. Results written to: {CSV_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
