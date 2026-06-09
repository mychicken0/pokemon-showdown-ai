#!/usr/bin/env python3
"""Pre-benchmark static audit: search local generation Pokédex for singleton abilities.

Saves results to logs/singleton_ability_local_dex_audit.csv
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from poke_env.data.gen_data import GenData
from bot_doubles_damage_aware import normalize_possible_abilities


def audit_singleton_abilities(gen=9):
    """Search local Pokédex for species/forms with exactly one legal ability."""
    dex = GenData.from_gen(gen).pokedex
    
    singleton_count = 0
    singleton_levitate_count = 0
    multi_ability_count = 0
    total_species = 0
    samples = []
    multi_levitate_samples = []
    
    for species_name, entry in dex.items():
        total_species += 1
        abilities = entry.get("abilities", {})
        norm_abilities = normalize_possible_abilities(abilities)
        
        if len(norm_abilities) == 1:
            singleton_count += 1
            the_ability = norm_abilities[0]
            if the_ability == "levitate":
                singleton_levitate_count += 1
                samples.append({
                    "species": species_name,
                    "ability": the_ability,
                    "type": "singleton_levitate",
                })
        elif len(norm_abilities) > 1:
            multi_ability_count += 1
            # Check if any is Levitate
            if "levitate" in norm_abilities:
                multi_levitate_samples.append({
                    "species": species_name,
                    "abilities": ",".join(norm_abilities),
                })
    
    return {
        "total_species": total_species,
        "singleton_count": singleton_count,
        "singleton_levitate_count": singleton_levitate_count,
        "multi_ability_count": multi_ability_count,
        "singleton_levitate_samples": samples,
        "multi_levitate_samples": multi_levitate_samples,
    }


def main():
    print("Searching local generation Pokédex for singleton abilities...")
    print("(No online lookup - using poke-env local data only)")
    print()
    
    result = audit_singleton_abilities(gen=9)
    
    print(f"Total species/forms in Gen 9 dex: {result['total_species']}")
    print(f"Species with exactly one ability: {result['singleton_count']}")
    print(f"Singleton Levitate forms: {result['singleton_levitate_count']}")
    print(f"Species with multiple abilities: {result['multi_ability_count']}")
    print()
    
    if result["singleton_levitate_samples"]:
        print("Singleton Levitate samples:")
        for s in result["singleton_levitate_samples"]:
            print(f"  {s['species']}: {s['ability']}")
    print()
    
    if result["multi_levitate_samples"]:
        print("Multi-ability species with Levitate (should NOT be deduced):")
        for s in result["multi_levitate_samples"]:
            print(f"  {s['species']}: {s['abilities']}")
    
    # Save to CSV
    os.makedirs("logs", exist_ok=True)
    for csv_path in ("logs/singleton_ability_local_dex_audit.csv", "logs/singleton_ability_local_dex_audit_phase635a.csv"):
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["type", "species", "ability", "abilities"])
            writer.writeheader()
            for s in result["singleton_levitate_samples"]:
                writer.writerow({"type": "singleton_levitate", "species": s["species"], "ability": s["ability"], "abilities": ""})
            for s in result["multi_levitate_samples"]:
                writer.writerow({"type": "multi_levitate", "species": s["species"], "ability": "", "abilities": s["abilities"]})
        print(f"Audit saved to {csv_path}")


if __name__ == "__main__":
    main()
