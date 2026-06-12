#!/usr/bin/env python3
"""
Manually fix RK9 team moves based on known correct data.
"""

import json

# Correct moves for the 3 RK9 teams we scraped
RK9_FIXES = {
    1: {
        "Venusaur": ["Sleep Powder", "Sludge Bomb", "Earth Power", "Protect"],
        "Charizard": ["Heat Wave", "Solar Beam", "Weather Ball", "Protect"],
        "Garchomp": ["Earthquake", "Rock Slide", "Stomping Tantrum", "Dragon Claw"],
        "Incineroar": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"],
        "Floette [Eternal Flower]": ["Moonblast", "Dazzling Gleam", "Calm Mind", "Protect"],
        "Sinistcha [Unremarkable Form]": ["Matcha Gotcha", "Rage Powder", "Trick Room", "Protect"],
    },
    2: {
        "Incineroar": ["Flare Blitz", "Parting Shot", "Throat Chop", "Fake Out"],
        "Floette [Eternal Flower]": ["Moonblast", "Dazzling Gleam", "Calm Mind", "Protect"],
        "Sneasler": ["Close Combat", "Dire Claw", "Fake Out", "Protect"],
        "Kingambit": ["Kowtow Cleave", "Sucker Punch", "Low Kick", "Protect"],
        "Gengar": ["Shadow Ball", "Sludge Bomb", "Thunderbolt", "Protect"],
        "Kommo-o": ["Clanging Scales", "Aura Sphere", "Clangorous Soul", "Protect"],
    },
    3: {
        "Sneasler": ["Protect", "Close Combat", "Dire Claw", "Fake Out"],
        "Sinistcha [Unremarkable Form]": ["Rage Powder", "Trick Room", "Matcha Gotcha", "Protect"],
        "Talonflame": ["Protect", "Brave Bird", "Flare Blitz", "Swords Dance"],
        "Steelix": ["Protect", "Heavy Slam", "High Horsepower", "Wide Guard"],
        "Rotom [Wash Rotom]": ["Will-O-Wisp", "Thunderbolt", "Hydro Pump", "Light Screen"],
        "Tyranitar": ["Protect", "Rock Slide", "Knock Off", "Dragon Dance"],
    },
    13: {
        "Corviknight": ["Brave Bird", "Tailwind", "Protect", "Iron Head"],
        "Tyranitar": ["Rock Slide", "Knock Off", "Protect", "Low Kick"],
        "Hydreigon": ["Dark Pulse", "Draco Meteor", "Earth Power", "Snarl"],
        "Froslass": ["Blizzard", "Protect", "Shadow Ball", "Weather Ball"],
        "Garchomp": ["Earthquake", "Dragon Claw", "Rock Slide", "Protect"],
        "Arcanine [Hisuian Form]": ["Protect", "Head Smash", "Extreme Speed", "Flare Blitz"],
    },
    52: {
        "Delphox": ["Mystical Fire", "Hyper Voice", "Psychic", "Protect"],
        "Sneasler": ["Fake Out", "Close Combat", "Dire Claw", "Protect"],
        "Sinistcha": ["Rage Powder", "Matcha Gotcha", "Life Dew", "Trick Room"],
        "Basculegion": ["Wave Crash", "Last Respects", "Aqua Jet", "Flip Turn"],
        "Incineroar": ["Fake Out", "Flare Blitz", "Parting Shot", "Throat Chop"],
        "Floette [Eternal Flower]": ["Moonblast", "Dazzling Gleam", "Light Of Ruin", "Protect"],
    },
}

def main():
    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/vgc2026_teams_detailed.json') as f:
        detailed = json.load(f)

    fixed = 0
    for team in detailed:
        rank = team.get("rank")
        if team.get("source") == "rk9" and rank in RK9_FIXES:
            fixes = RK9_FIXES[rank]
            for p in team.get("pokemon", []):
                species = p.get("species")
                if species in fixes:
                    old = p.get("moves", [])
                    p["moves"] = fixes[species]
                    if old != fixes[species]:
                        print(f"Fixed Rank {rank} {species}: {old} -> {fixes[species]}")
                        fixed += 1

    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/vgc2026_teams_detailed.json', 'w') as f:
        json.dump(detailed, f, indent=2)

    print(f"Fixed {fixed} pokemon moves")
    print("Done!")

if __name__ == "__main__":
    main()