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
CSV_PATH = "logs/doubles_ability_hard_safety_phase631_confirmation.csv"

def count_audit_ability_metrics(log_path):
    metrics = {
        "protect_cnt": 0,
        "spread_cnt": 0,
        "focus_fire_cnt": 0,
        "zero_eff_cnt": 0,
        "all_imm_cnt": 0,
        "hard_block_avoided": 0,
        "immune_move_selected": 0,
        "ground_into_levitate": 0,
        "ally_safe_spread": 0,
        "redirection_avoided": 0,
        "ground_block_avoided_win": 0,
        "ground_block_avoided_loss": 0,
        "absorb_block_avoided_win": 0,
        "absorb_block_avoided_loss": 0,
        "redirection_avoided_win": 0,
        "redirection_avoided_loss": 0,
        "optional_block_avoided_win": 0,
        "optional_block_avoided_loss": 0,
        "immune_singletarget_selected_win": 0,
        "immune_singletarget_selected_loss": 0,
        "partial_immune_spread_selected_win": 0,
        "partial_immune_spread_selected_loss": 0,
        "partial_ability_immune_spread_selected_win": 0,
        "partial_ability_immune_spread_selected_loss": 0
    }

    if not os.path.exists(log_path):
        return metrics

    with open(log_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                won = bool(battle.get("won", False))
                for turn in battle.get("audit_turns", []):
                    if turn.get("focus_fire_triggered"):
                        metrics["focus_fire_cnt"] += 1
                        
                    for slot_key in ("slot_0", "slot_1"):
                        slot = turn.get(slot_key, {})
                        if not slot:
                            continue
                        
                        is_protect = bool(slot.get("action_types", {}).get("protect"))
                        is_spread = bool(slot.get("action_types", {}).get("spread"))
                        is_zero_eff = bool(slot.get("zero_effectiveness_move_selected"))
                        is_all_imm = bool(slot.get("all_targets_immune_spread_selected"))
                        is_hard_avoid = bool(slot.get("ability_hard_block_avoided"))
                        is_imm_selected = bool(slot.get("ability_immune_move_selected"))
                        is_ground_lev = bool(slot.get("ground_into_levitate_selected"))
                        is_ally_safe = bool(slot.get("ally_ability_safe_spread"))
                        is_red_avoid = bool(slot.get("ability_redirection_avoided"))
                        is_partial_spread = bool(slot.get("partial_immune_spread_selected"))
                        is_partial_ability_spread = bool(slot.get("partial_ability_immune_spread_selected"))
                        
                        if is_protect:
                            metrics["protect_cnt"] += 1
                        if is_spread:
                            metrics["spread_cnt"] += 1
                        if is_zero_eff:
                            metrics["zero_eff_cnt"] += 1
                        if is_all_imm:
                            metrics["all_imm_cnt"] += 1
                        if is_hard_avoid:
                            metrics["hard_block_avoided"] += 1
                        if is_imm_selected:
                            metrics["immune_move_selected"] += 1
                        if is_ground_lev:
                            metrics["ground_into_levitate"] += 1
                        if is_ally_safe:
                            metrics["ally_safe_spread"] += 1
                        if is_red_avoid:
                            metrics["redirection_avoided"] += 1
                            
                        # Reason-level classification for hard block avoided
                        reason = slot.get("ability_block_reason", "")
                        
                        if is_hard_avoid:
                            # Ground blocks
                            if reason.startswith("ground_"):
                                if won:
                                    metrics["ground_block_avoided_win"] += 1
                                else:
                                    metrics["ground_block_avoided_loss"] += 1
                            # Absorb blocks
                            elif reason.startswith(("water_into_", "electric_into_", "fire_into_", "grass_into_")):
                                if won:
                                    metrics["absorb_block_avoided_win"] += 1
                                else:
                                    metrics["absorb_block_avoided_loss"] += 1
                            # Optional blocks
                            elif reason.startswith(("sound_into_", "bullet_into_", "explosion_into_")):
                                if won:
                                    metrics["optional_block_avoided_win"] += 1
                                else:
                                    metrics["optional_block_avoided_loss"] += 1
                                    
                        # Redirection avoided
                        if is_red_avoid:
                            if won:
                                metrics["redirection_avoided_win"] += 1
                            else:
                                metrics["redirection_avoided_loss"] += 1
                                
                        # Selected immune single-target count
                        if is_imm_selected and not is_spread:
                            if won:
                                metrics["immune_singletarget_selected_win"] += 1
                            else:
                                metrics["immune_singletarget_selected_loss"] += 1
                                
                        # Selected partial ability-immune spread count
                        if is_partial_spread:
                            if won:
                                metrics["partial_immune_spread_selected_win"] += 1
                            else:
                                metrics["partial_immune_spread_selected_loss"] += 1

                        # Selected partial ability-only spread count
                        if is_partial_ability_spread:
                            if won:
                                metrics["partial_ability_immune_spread_selected_win"] += 1
                            else:
                                metrics["partial_ability_immune_spread_selected_loss"] += 1
            except Exception:
                continue
                
    return metrics

async def run_matchup(name, config, opp_class, n_battles, log_path, label):
    suffix = random.randint(1000, 9999)
    bot_name = f"Safety_{label}_{suffix}"[:18]
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

    if opp_class == DoublesDamageAwarePlayer:
        # Head-to-head (on vs off)
        config_off = DoublesDamageAwareConfig(
            enable_type_immunity_safety=True,
            enable_self_drop_move_penalty=True,
            enable_partial_spread_immunity_penalty=True,
            enable_speed_priority_awareness=True,
            enable_order_aware_overkill=False,
            enable_ability_hard_safety_only=False,
            enable_ability_awareness=False,
            enable_meta_opponent_modeling=False,
            enable_random_set_opponent_modeling=False
        )
        opponent = DoublesDamageAwarePlayer(
            account_configuration=AccountConfiguration(opp_name, None),
            verbose=False,
            config=config_off,
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

    m = count_audit_ability_metrics(log_path)

    print(f"Run {label} Finished: {wins} Wins | {losses} Losses | Win Rate: {win_rate:.2f}% | Avg Turns: {avg_turns:.2f}")
    print(f"  Protect: {m['protect_cnt']} | Spread: {m['spread_cnt']} | Focus-fire: {m['focus_fire_cnt']}")
    print(f"  Hard blocks avoided: {m['hard_block_avoided']} | Immune moves selected: {m['immune_move_selected']}")
    print(f"  Ground avoided (win/loss): {m['ground_block_avoided_win']}/{m['ground_block_avoided_loss']}")
    print(f"  Absorb avoided (win/loss): {m['absorb_block_avoided_win']}/{m['absorb_block_avoided_loss']}")
    print(f"  Redirections avoided (win/loss): {m['redirection_avoided_win']}/{m['redirection_avoided_loss']}")
    print(f"  Optional avoided (win/loss): {m['optional_block_avoided_win']}/{m['optional_block_avoided_loss']}")
    print(f"  Immune single-target selected (win/loss): {m['immune_singletarget_selected_win']}/{m['immune_singletarget_selected_loss']}")
    print(f"  Partial spread selected (win/loss): {m['partial_immune_spread_selected_win']}/{m['partial_immune_spread_selected_loss']}")
    print(f"  Partial ability spread selected (win/loss): {m['partial_ability_immune_spread_selected_win']}/{m['partial_ability_immune_spread_selected_loss']}")

    return {
        "matchup": name,
        "win_rate": f"{win_rate:.2f}",
        "avg_turns": f"{avg_turns:.2f}",
        **m
    }

async def main():
    os.makedirs("logs", exist_ok=True)

    # Setup the configurations for our confirmation runs
    config_off = DoublesDamageAwareConfig(
        enable_type_immunity_safety=True,
        enable_self_drop_move_penalty=True,
        enable_partial_spread_immunity_penalty=True,
        enable_speed_priority_awareness=True,
        enable_order_aware_overkill=False,
        enable_ability_hard_safety_only=False,
        enable_ability_awareness=False,
        enable_meta_opponent_modeling=False,
        enable_random_set_opponent_modeling=False
    )

    config_ground_only = DoublesDamageAwareConfig(
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

    # Run 1: Off vs Basic: 500
    r1 = await run_matchup(
        name="Off vs Basic",
        config=config_off,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=500,
        log_path="logs/doubles_phase631_run1.jsonl",
        label="1"
    )
    runs_data.append(r1)

    # Run 2: Ground Target Only vs Basic: 500
    r2 = await run_matchup(
        name="Ground Target Only vs Basic",
        config=config_ground_only,
        opp_class=DoublesBasicAwarePlayer,
        n_battles=500,
        log_path="logs/doubles_phase631_run2.jsonl",
        label="2"
    )
    runs_data.append(r2)

    # Run 3: Ground Target Only vs Off: 500
    r3 = await run_matchup(
        name="Ground Target Only vs Off",
        config=config_ground_only,
        opp_class=DoublesDamageAwarePlayer,
        n_battles=500,
        log_path="logs/doubles_phase631_run3.jsonl",
        label="3"
    )
    runs_data.append(r3)

    # Run 4: Ground Target Only vs SafeRandom: 100
    r4 = await run_matchup(
        name="Ground Target Only vs SafeRandom",
        config=config_ground_only,
        opp_class=DoublesSafeRandomPlayer,
        n_battles=100,
        log_path="logs/doubles_phase631_run4.jsonl",
        label="4"
    )
    runs_data.append(r4)

    # Save to CSV
    fieldnames = [
        "matchup", "win_rate", "avg_turns", "protect_cnt", "spread_cnt", "focus_fire_cnt",
        "zero_eff_cnt", "all_imm_cnt", "hard_block_avoided", "immune_move_selected",
        "ground_into_levitate", "ally_safe_spread", "redirection_avoided",
        "ground_block_avoided_win", "ground_block_avoided_loss",
        "absorb_block_avoided_win", "absorb_block_avoided_loss",
        "redirection_avoided_win", "redirection_avoided_loss",
        "optional_block_avoided_win", "optional_block_avoided_loss",
        "immune_singletarget_selected_win", "immune_singletarget_selected_loss",
        "partial_immune_spread_selected_win", "partial_immune_spread_selected_loss",
        "partial_ability_immune_spread_selected_win", "partial_ability_immune_spread_selected_loss"
    ]
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in runs_data:
            writer.writerow(row)

    print(f"\nAll phase 6.3.1 confirmation benchmark matchups finished. Results written to: {CSV_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
