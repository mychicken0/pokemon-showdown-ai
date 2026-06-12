#!/usr/bin/env python3
"""
Showdown Species Name Normalizer

Normalizes display names from various sources (Pikalytics, Limitless, RK9, etc.)
into Showdown-compatible species IDs.
"""

from typing import Dict, Optional
import json
import re
from pathlib import Path

# Maps display names to Showdown species IDs
DISPLAY_TO_SHOWDOWN: Dict[str, str] = {
    # Standard names (identity mapping for base forms)
    "Abomasnow": "abomasnow",
    "Aegislash": "aegislash",
    "Aerodactyl": "aerodactyl",
    "Ampharos": "ampharos",
    "Araquanid": "araquanid",
    "Arcanine": "arcanine",
    "Archaludon": "archaludon",
    "Basculegion": "basculegion",
    "Blastoise": "blastoise",
    "Camerupt": "camerupt",
    "Ceruledge": "ceruledge",
    "Chandelure": "chandelure",
    "Charizard": "charizard",
    "Clefable": "clefable",
    "Corviknight": "corviknight",
    "Crabominable": "crabominable",
    "Delphox": "delphox",
    "Dragonite": "dragonite",
    "Drampa": "drampa",
    "Empoleon": "empoleon",
    "Espathra": "espathra",
    "Excadrill": "excadrill",
    "Farigiraf": "farigiraf",
    "Floette": "floette",
    "Froslass": "froslass",
    "Gallade": "gallade",
    "Garchomp": "garchomp",
    "Gardevoir": "gardevoir",
    "Gengar": "gengar",
    "Glimmora": "glimmora",
    "Gourgeist": "gourgeist",
    "Gyarados": "gyarados",
    "Hatterene": "hatterene",
    "Hawlucha": "hawlucha",
    "Hydrapple": "hydrapple",
    "Hydreigon": "hydreigon",
    "Incineroar": "incineroar",
    "Kangaskhan": "kangaskhan",
    "Kingambit": "kingambit",
    "Kleavor": "kleavor",
    "Kommo-o": "kommoo",
    "Krookodile": "krookodile",
    "Lopunny": "lopunny",
    "Luxray": "luxray",
    "Mamoswine": "mamoswine",
    "Maushold": "maushold",
    "Meganium": "meganium",
    "Meowscarada": "meowscarada",
    "Milotic": "milotic",
    "Mimikyu": "mimikyu",
    "Oranguru": "oranguru",
    "Orthworm": "orthworm",
    "Palafin": "palafin",
    "Pelipper": "pelipper",
    "Pikachu": "pikachu",
    "Pinsir": "pinsir",
    "Politoed": "politoed",
    "Primarina": "primarina",
    "Sableye": "sableye",
    "Salazzle": "salazzle",
    "Scizor": "scizor",
    "Scovillain": "scovillain",
    "Sinistcha": "sinistcha",
    "Skarmory": "skarmory",
    "Slowbro": "slowbro",
    "Sneasler": "sneasler",
    "Snorlax": "snorlax",
    "Steelix": "steelix",
    "Sylveon": "sylveon",
    "Talonflame": "talonflame",
    "Tinkaton": "tinkaton",
    "Torkoal": "torkoal",
    "Torterra": "torterra",
    "Toxapex": "toxapex",
    "Tsareena": "tsareena",
    "Tyranitar": "tyranitar",
    "Venusaur": "venusaur",
    "Vivillon": "vivillon",
    "Volcarona": "volcarona",
    "Whimsicott": "whimsicott",

    # Alolan forms
    "Alolan Ninetales": "ninetalesalola",

    # Hisuian forms
    "Arcanine [Hisuian Form]": "arcaninehisui",
    "Hisuian Arcanine": "arcaninehisui",
    "Hisuian Goodra": "goodrahisui",
    "Hisuian Samurott": "samurotthisui",
    "Hisuian Zoroark": "zoroarkhisui",

    # Eternal Flower Floette
    "Eternal Flower Floette": "floetteeternal",
    "Floette [Eternal Flower]": "floetteeternal",

    # Sinistcha forms
    "Sinistcha [Unremarkable Form]": "sinistcha",
    "Sinistcha [Masterpiece Form]": "sinistchamasterpiece",

    # Rotom forms
    "Heat Rotom": "rotomheat",
    "Wash Rotom": "rotomwash",
    "Mow Rotom": "rotommow",
    "Fan Rotom": "rotomfan",
    "Frost Rotom": "rotomfrost",
    "Rotom [Wash Rotom]": "rotomwash",

    # Basculegion forms
    "Basculegion ♀": "basculegionf",
    "Basculegion-F": "basculegionf",

    # Paldean Tauros forms
    "Paldean Tauros Aqua Breed": "taurospaldeaaqua",
    "Paldean Tauros Blaze Breed": "taurospaldeablaze",
    "Paldean Tauros Combat Breed": "taurospaldeacombat",

    # Urshifu forms
    "Urshifu [Single Strike]": "urshifusingle",
    "Urshifu [Rapid Strike]": "urshifurapid",
    "Urshifu-Single": "urshifusingle",
    "Urshifu-Rapid": "urshifurapid",

    # Ogerpon forms
    "Ogerpon [Teal Mask]": "ogerpon",
    "Ogerpon [Wellspring Mask]": "ogerponwellspring",
    "Ogerpon [Hearthflame Mask]": "ogerponhearthflame",
    "Ogerpon [Cornerstone Mask]": "ogerponcornerstone",

    # Calyrex forms
    "Calyrex [Ice Rider]": "calyrexice",
    "Calyrex [Shadow Rider]": "calyrexshadow",

    # Indeedee forms
    "Indeedee [Male]": "indeedee",
    "Indeedee [Female]": "indeedeef",

    # Landorus/Tornadus/Thundurus forms
    "Landorus [Therian]": "landorustherian",
    "Landorus [Incarnate]": "landorus",
    "Tornadus [Therian]": "tornadustherian",
    "Tornadus [Incarnate]": "tornadus",
    "Thundurus [Therian]": "thundurustherian",
    "Thundurus [Incarnate]": "thundurus",

    # Terapagos forms
    "Terapagos [Normal]": "terapagos",
    "Terapagos [Terastal]": "terapagostera",
    "Terapagos [Stellar]": "terapagosstellar",

    # Enamorus forms
    "Enamorus [Therian]": "enamorustherian",
    "Enamorus [Incarnate]": "enamorus",

    # Zacian/Zamazenta forms
    "Zacian [Crowned]": "zaciancrowned",
    "Zacian [Hero]": "zacian",
    "Zamazenta [Crowned]": "zamazentacrowned",
    "Zamazenta [Hero]": "zamazenta",

    # Kyurem forms
    "Kyurem [White]": "kyuremwhite",
    "Kyurem [Black]": "kyuremblack",

    # Necrozma forms
    "Necrozma [Dusk Mane]": "necrozmaduskmane",
    "Necrozma [Dawn Wings]": "necrozmadawnwings",
    "Necrozma [Ultra]": "necrozmaultra",

    # Zygarde forms
    "Zygarde [10%]": "zygarde10",
    "Zygarde [Complete]": "zygardecomplete",

    # Hoopa forms
    "Hoopa [Unbound]": "hoopaunbound",

    # Shaymin forms
    "Shaymin [Sky]": "shayminsky",

    # Giratina forms
    "Giratina [Origin]": "giratinaorigin",

    # Meloetta forms
    "Meloetta [Pirouette]": "meloettapirouette",

    # Palafin forms
    "Palafin [Hero]": "palafin",

    # Tatsugiri forms
    "Tatsugiri [Curly]": "tatsugiri",
    "Tatsugiri [Droopy]": "tatsugiridroopy",
    "Tatsugiri [Stretchy]": "tatsugiristretchy",

    # Dudunsparce forms
    "Dudunsparce [Two-Segment]": "dudunsparce",
    "Dudunsparce [Three-Segment]": "dudunsparcethreesegment",

    # Maushold forms
    "Maushold [Family of Four]": "maushold",
    "Maushold [Family of Three]": "mausholdthree",

    # Squawkabilly forms
    "Squawkabilly [Green]": "squawkabilly",
    "Squawkabilly [Blue]": "squawkabillyblue",
    "Squawkabilly [Yellow]": "squawkabillyyellow",
    "Squawkabilly [White]": "squawkabillywhite",

    # Gimmighoul forms
    "Gimmighoul [Chest]": "gimmighoul",
    "Gimmighoul [Roaming]": "gimmighoulroaming",

    # Koraidon/Miraidon forms
    "Koraidon [Battle]": "koraidon",
    "Miraidon [Battle]": "miraidon",
}

# Reverse mapping for validation
SHOWDOWN_TO_DISPLAY: Dict[str, str] = {v: k for k, v in DISPLAY_TO_SHOWDOWN.items()}


def normalize_species(display_name: str) -> Optional[str]:
    """
    Normalize a display name to Showdown species ID.
    Returns None if not found.
    """
    # Direct match
    if display_name in DISPLAY_TO_SHOWDOWN:
        return DISPLAY_TO_SHOWDOWN[display_name]

    # Try removing brackets and extra spaces
    cleaned = display_name.strip()
    # Remove [Form] suffixes
    cleaned = re.sub(r'\s*\[.*?\]\s*', '', cleaned).strip()
    if cleaned in DISPLAY_TO_SHOWDOWN:
        return DISPLAY_TO_SHOWDOWN[cleaned]

    # Try case-insensitive matching
    for key, val in DISPLAY_TO_SHOWDOWN.items():
        if key.lower() == display_name.lower():
            return val

    return None


def normalize_team_species(pokemon_list: list) -> list:
    """Normalize all species in a team's pokemon list."""
    result = []
    for p in pokemon_list:
        normalized = normalize_species(p.get("species", ""))
        if normalized:
            p = p.copy()
            p["species"] = normalized
            p["showdown_species_id"] = normalized
        result.append(p)
    return result


def validate_species_exists(showdown_id: str) -> bool:
    """Check if a Showdown species ID exists in local dex."""
    # This would require loading the local Showdown dex
    # For now, we trust our mapping
    return showdown_id in set(DISPLAY_TO_SHOWDOWN.values())


def main():
    """Test the normalizer against our dataset."""
    # Load directly
    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_topteams/vgc2026_top200_full_teams.json') as f:
        data = json.load(f)

    species_found = set()
    species_not_found = set()

    for team in data['teams']:
        if team['parse_status'] == 'complete':
            for p in team['team']:
                original = p['species']
                normalized = normalize_species(original)
                if normalized:
                    species_found.add((original, normalized))
                else:
                    species_not_found.add(original)

    print(f"Species successfully normalized: {len(species_found)}")
    for orig, norm in sorted(species_found):
        print(f"  {orig} -> {norm}")

    if species_not_found:
        print(f"\nSpecies NOT found in mapping: {len(species_not_found)}")
        for s in sorted(species_not_found):
            print(f"  {s}")
    else:
        print("\nAll species normalized successfully!")


if __name__ == "__main__":
    main()