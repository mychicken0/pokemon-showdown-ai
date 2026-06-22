#!/usr/bin/env python3
"""Local diagnostic script: inspect runtime opponent singleton ability state.

Supports:
  --species
  --battle
  --filepath
"""
import argparse
import json
import os
import sys

def parse_args():
    parser = argparse.ArgumentParser(description="Inspect runtime singleton ability state")
    parser.add_argument("--filepath", default="logs/doubles_decision_audit.jsonl", help="Path to jsonl audit log")
    parser.add_argument("--species", help="Filter by species name (case-insensitive)")
    parser.add_argument("--battle", help="Filter by battle tag")
    return parser.parse_args()

def main():
    args = parse_args()
    
    if not os.path.exists(args.filepath):
        print(f"Error: log file {args.filepath} not found.")
        sys.exit(1)
        
    species_filter = args.species.lower().replace(" ", "").replace("-", "") if args.species else None
    battle_filter = args.battle.strip() if args.battle else None
    
    print(f"Analyzing {args.filepath}...")
    print(f"Filters: species={args.species}, battle={args.battle}")
    print("-" * 80)
    
    count = 0
    with open(args.filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                battle = json.loads(line)
                battle_tag = battle.get("battle_tag", "")
                
                if battle_filter and battle_tag != battle_filter:
                    continue
                    
                turns = battle.get("audit_turns", [])
                for turn_data in turns:
                    turn_num = turn_data.get("turn", 0)
                    opponents = turn_data.get("opponent_actives_state", [])
                    
                    for opp in opponents:
                        if not opp:
                            continue
                        
                        species = opp.get("species", "")
                        norm_species = species.lower().replace(" ", "").replace("-", "")
                        
                        if species_filter and species_filter not in norm_species:
                            continue
                            
                        count += 1
                        print(f"Battle Tag: {battle_tag} | Turn: {turn_num}")
                        print(f"  Opponent Species/Form: {species}")
                        print(f"  pokemon.ability: {opp.get('ability')}")
                        print(f"  pokemon.temporary_ability: {opp.get('temporary_ability')}")
                        print(f"  raw pokemon.possible_abilities: {opp.get('possible_abilities')}")
                        print(f"  normalized possible abilities: {opp.get('normalized_possible_abilities')}")
                        print(f"  resolver output (ability): {opp.get('resolved_ability')}")
                        print(f"  resolver source: {opp.get('resolved_source')}")
                        print(f"  singleton flag state: {opp.get('singleton_flag_state')}")
                        print(f"  Ground blocked: {opp.get('ground_blocked')}")
                        print("-" * 50)
            except Exception as e:
                # print(f"Error parsing line: {e}")
                pass
                
    print(f"Total matching turns/opponents found: {count}")

if __name__ == "__main__":
    main()
