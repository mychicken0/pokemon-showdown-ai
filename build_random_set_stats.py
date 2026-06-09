#!/usr/bin/env python3
"""
build_random_set_stats.py

Phase 5.1: Build the gen9randomdoublesbattle random set database.

Reads the local Pokémon Showdown source file:
    ../pokemon-showdown/data/random-battles/gen9/doubles-sets.json

Extracts species, moves, abilities and computes equal probabilities
for each item in the pool (since the source only provides pools, not
real usage percentages).

Saves to:
    data/random_doubles_set_stats.json

Output schema:
{
  "format": "gen9randomdoublesbattle",
  "source": "estimated_from_random_set_pool",
  "pokemon": {
    "speciesid": {
      "moves": { "moveid": probability },
      "abilities": { "abilityid": probability },
      "items": {}
    }
  }
}
"""
import json
import os
import sys


# ---------------------------------------------------------------------------
# Normalization helpers (must match random_set_model.py)
# ---------------------------------------------------------------------------

def normalize_species(name: str) -> str:
    if not name:
        return ""
    return "".join(c.lower() for c in str(name) if c.isalnum())


def normalize_move(name: str) -> str:
    if not name:
        return ""
    return "".join(c.lower() for c in str(name) if c.isalnum())


def normalize_ability(name: str) -> str:
    if not name:
        return ""
    return "".join(c.lower() for c in str(name) if c.isalnum())


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_random_doubles_set_stats(
    source_path: str,
    output_path: str,
) -> dict:
    """
    Parse doubles-sets.json and build the flat probability database.

    For each species:
    - All moves across all sets are merged into one pool (deduplicated).
    - Each move is assigned equal probability = 1 / pool_size.
      If a move appears in more sets, it gets a proportionally higher
      fractional score (weighted by # sets it appears in / total sets).
    - Abilities are merged similarly.
    - Items are left empty (not available in this source).

    Returns the built database dict.
    """
    if not os.path.exists(source_path):
        print(f"[ERROR] Source file not found: {source_path}")
        sys.exit(1)

    print(f"Loading source: {source_path}")
    with open(source_path, "r") as f:
        raw_data = json.load(f)

    print(f"Total species in source: {len(raw_data)}")

    pokemon_db = {}
    total_moves_loaded = 0
    total_abilities_loaded = 0
    skipped = 0

    for species_id, entry in raw_data.items():
        norm_id = normalize_species(species_id)
        if not norm_id:
            skipped += 1
            continue

        sets = entry.get("sets", [])
        if not sets:
            skipped += 1
            continue

        num_sets = len(sets)

        # ------------------------------------------------------------------
        # Merge moves: weight by how many sets include the move
        # ------------------------------------------------------------------
        move_counts: dict = {}
        for s in sets:
            pool = s.get("movepool", [])
            # Each move in this set's pool counts +1
            for move_name in pool:
                norm_m = normalize_move(move_name)
                if norm_m:
                    move_counts[norm_m] = move_counts.get(norm_m, 0) + 1

        # Compute probabilities: count / num_sets (capped at 1.0)
        # This gives higher probability to moves appearing in more sets.
        moves_prob = {}
        for move_id, count in move_counts.items():
            prob = min(1.0, round(count / num_sets, 4))
            moves_prob[move_id] = prob

        # ------------------------------------------------------------------
        # Merge abilities: weight by how many sets include the ability
        # ------------------------------------------------------------------
        ability_counts: dict = {}
        for s in sets:
            abilities_list = s.get("abilities", [])
            for ab_name in abilities_list:
                norm_ab = normalize_ability(ab_name)
                if norm_ab:
                    ability_counts[norm_ab] = ability_counts.get(norm_ab, 0) + 1

        # Compute ability probabilities: count / num_sets (capped at 1.0)
        abilities_prob = {}
        for ab_id, count in ability_counts.items():
            prob = min(1.0, round(count / num_sets, 4))
            abilities_prob[ab_id] = prob

        # ------------------------------------------------------------------
        # Items: not available in this source; leave empty
        # ------------------------------------------------------------------
        items_prob = {}

        pokemon_db[norm_id] = {
            "moves": moves_prob,
            "abilities": abilities_prob,
            "items": items_prob,
        }

        total_moves_loaded += len(moves_prob)
        total_abilities_loaded += len(abilities_prob)

    # ------------------------------------------------------------------
    # Add cosmetic/regional form aliases.
    # These are alternate form IDs that poke-env may report in battle
    # but which map to the same base form set in the Showdown source.
    # We copy the base form's data to cover these alias IDs.
    # ------------------------------------------------------------------
    FORM_ALIASES = {
        # minior colored forms -> minior
        "miniorred": "minior", "miniororange": "minior", "minioryellow": "minior",
        "miniorgreen": "minior", "miniorblue": "minior", "miniorindigo": "minior",
        "miniorviolet": "minior",
        # polteageist forms -> polteageist
        "polteageistantique": "polteageist",
        # sinistcha forms -> sinistcha
        "sinistchamasterpiece": "sinistcha",
        # gastrodon east -> gastrodon
        "gastrodoneast": "gastrodon",
        # alcremie forms -> alcremie (many cream flavors)
        "alcremiematchacream": "alcremie", "alcremierubycream": "alcremie",
        "alcremiemintcream": "alcremie", "alcremielemonncream": "alcremie",
        "alcremiesaltedcream": "alcremie", "alcremierubyswirl": "alcremie",
        "alcremiecaramelswirl": "alcremie", "alcremierainbowswirl": "alcremie",
        "alcremieribbonsweet": "alcremie",
        # magearna original -> magearna
        "magearnaoriginal": "magearna",
        # vivillon patterns -> vivillon
        "vivillonmodern": "vivillon", "vivillonsandstorm": "vivillon",
        "vivillonhighplains": "vivillon", "vivillonmeadow": "vivillon",
        "vivillonicysnow": "vivillon", "vivillonpolar": "vivillon",
        "vivillontundra": "vivillon", "vivillonarchipelago": "vivillon",
        "vivillonelegant": "vivillon", "vivillongarden": "vivillon",
        "vivillonriver": "vivillon", "vivillonmonsoon": "vivillon",
        "vivillonsavanna": "vivillon", "vivillonsun": "vivillon",
        "vivillonwave": "vivillon", "vivillonmarine": "vivillon",
        "vivillonseasonal": "vivillon", "vivillontropical": "vivillon",
        "vivillonjungle": "vivillon", "vivillonfancy": "vivillon",
        "vivillonpokeball": "vivillon",
        # maushold forms -> maushold
        "mausholdfour": "maushold", "maushold": "maushold",
        # pikachu regional/cap forms -> pikachu
        "pikachuoriginal": "pikachu", "pikachuhoenn": "pikachu",
        "pikachusinnoh": "pikachu", "pikachuunova": "pikachu",
        "pikachukalos": "pikachu", "pikachualola": "pikachu",
        "pikachupartner": "pikachu", "pikachuworld": "pikachu",
        "pikachugmax": "pikachu",
        # toxtricity forms -> toxtricity
        "toxtricitylow": "toxtricity", "toxtricitylowkey": "toxtricity",
        # lycanroc forms -> lycanroc
        "lycanrocmidnight": "lycanroc", "lycanrocdusk": "lycanroc",
        # eiscue forms -> eiscue
        "eiscuenoice": "eiscue",
        # morpeko forms -> morpeko
        "morpekohangry": "morpeko",
    }

    for alias_id, base_id in FORM_ALIASES.items():
        if alias_id not in pokemon_db and base_id in pokemon_db:
            # Deep copy is not needed since we are just reading the data
            pokemon_db[alias_id] = pokemon_db[base_id]

    # Build the final database
    database = {
        "format": "gen9randomdoublesbattle",
        "source": "estimated_from_random_set_pool",
        "note": (
            "Probabilities are estimated from the local Pokémon Showdown "
            "random doubles set pools. A move that appears in all of a "
            "species' sets gets probability 1.0; a move that appears in "
            "half the sets gets 0.5. These are NOT real usage percentages. "
            "Cosmetic form aliases are included and map to their base form data."
        ),
        "pokemon": pokemon_db,
    }

    # Save output
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(database, f, indent=2)

    return database


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Resolve paths relative to this script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Source: local Pokémon Showdown doubles sets JSON
    source_path = os.path.join(
        script_dir, "..", "pokemon-showdown",
        "data", "random-battles", "gen9", "doubles-sets.json"
    )
    source_path = os.path.normpath(source_path)

    # Output
    output_path = os.path.join(script_dir, "data", "random_doubles_set_stats.json")

    print("=" * 60)
    print("  Phase 5.1 Random Set Database Builder")
    print("=" * 60)
    print(f"  Source : {source_path}")
    print(f"  Output : {output_path}")
    print("=" * 60)

    db = build_random_doubles_set_stats(source_path, output_path)
    pokemon_db = db.get("pokemon", {})

    # Compute totals
    total_species = len(pokemon_db)
    total_moves = sum(len(e.get("moves", {})) for e in pokemon_db.values())
    total_abilities = sum(len(e.get("abilities", {})) for e in pokemon_db.values())
    total_items = sum(len(e.get("items", {})) for e in pokemon_db.values())

    print()
    print("=" * 60)
    print("  Build Complete!")
    print("=" * 60)
    print(f"  Species loaded     : {total_species}")
    print(f"  Move entries       : {total_moves}")
    print(f"  Ability entries    : {total_abilities}")
    print(f"  Item entries       : {total_items} (no items in source)")
    print(f"  Output path        : {output_path}")
    print("=" * 60)
    print()
    print("NOTE: Probabilities are estimated from the random set pool,")
    print("      NOT real usage percentages.")
    print()

    # Print a quick sample
    sample_species = list(pokemon_db.keys())[:3]
    for sp in sample_species:
        entry = pokemon_db[sp]
        top_moves = sorted(entry["moves"].items(), key=lambda x: x[1], reverse=True)[:4]
        top_abilities = sorted(entry["abilities"].items(), key=lambda x: x[1], reverse=True)[:2]
        print(f"  [{sp}]")
        print(f"    Moves     : {top_moves}")
        print(f"    Abilities : {top_abilities}")
        print()


if __name__ == "__main__":
    main()
