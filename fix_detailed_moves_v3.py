#!/usr/bin/env python3
"""
Reconstruct moves in the detailed teams file - comprehensive fix.
"""

import json

# Complete known multi-word moves dictionary for Gen 9 VGC
MOVE_PAIRS = {
    # Sleep moves
    "sleep powder", "stun powder", "poison powder", "rage powder", "cotton guard",
    # Rock moves
    "rock slide", "rock tomb", "rock throw", "rock blast", "rock polish", "rock wrecker",
    "rock climb",
    # Dragon moves
    "dragon claw", "dragon pulse", "dragon dance", "dragon tail", "draco meteor", "dragon darts",
    "dragon energy", "dragon rush", "dragon breath", "dragon rage",
    # Stomping
    "stomping tantrum",
    # Dual
    "dual wingbeat", "dual chop",
    # Dark
    "dark pulse", "dark void", "darkest lariat",
    # Shadow
    "shadow ball", "shadow claw", "shadow sneak", "shadow bone", "shadow force",
    # Ice
    "ice beam", "ice punch", "ice fang", "ice shard", "ice hammer", "ice spinner",
    # Thunder
    "thunderbolt", "thunder punch", "thunder fang", "thunder wave", "thundercage", "thundershock",
    "thunder cage",
    # Solar
    "solar beam", "solar blade", "solar flare",
    # Focus
    "focus blast", "focus punch", "focus energy",
    # Fake
    "fake out", "fake tears",
    # Flare
    "flare blitz",
    # Swords
    "swords dance",
    # Cross
    "cross chop", "cross poison",
    # Leaf
    "leaf blade", "leaf storm", "leaf tornado", "leafage",
    # Will
    "will-o-wisp",
    # Hyper
    "hyper voice", "hyper beam", "hyper fang", "hyper drill",
    # Close
    "close combat",
    # Dire
    "dire claw",
    # Wide
    "wide guard",
    # High
    "high horsepower",
    # Heavy
    "heavy slam",
    # Light
    "light screen", "light of ruin",
    # Calm
    "calm mind",
    # Trick
    "trick room",
    # Matcha
    "matcha gotcha",
    # Drain
    "drain punch", "drain kiss", "draining kiss",
    # Life
    "life dew",
    # Weather
    "weather ball",
    # Electro
    "electro shot", "electro ball", "electroweb", "electro drift",
    # Clanging
    "clanging scales", "clangorous soul", "clangorous soulblaze",
    # Shell
    "shell smash", "shell trap", "shell side arm",
    # Head
    "head smash", "headlong rush", "head charge",
    # Extreme
    "extreme speed", "extreme evoboost",
    # Giga
    "giga drain", "giga impact",
    # Brave
    "brave bird",
    # Air
    "air slash", "air cutter",
    # Heat
    "heat wave", "heat crash",
    # Aqua
    "aqua jet", "aqua tail", "aqua cutter", "aqua step", "aqua ring",
    # Scale
    "scale shot",
    # Spiky
    "spiky shield",
    # Power
    "power gem", "power trip", "power whip", "power split",
    # Bullet
    "bullet punch", "bullet seed",
    # Iron
    "iron head", "iron defense", "iron tail",
    # Sucker
    "sucker punch",
    # Kowtow
    "kowtow cleave",
    # Low
    "low kick", "low sweep",
    # Quick
    "quick attack", "quick guard",
    # Vacuum
    "vacuum wave",
    # Blaze
    "blaze kick",
    # Parting
    "parting shot",
    # Throat
    "throat chop",
    # Dazzling
    "dazzling gleam",
    # Moon
    "moonblast", "moonlight",
    # Psychic
    "psychic", "psychic fangs", "psychic noise", "psychic terrain",
    # Fire
    "fire blast", "fire punch", "fire fang", "fire spin", "fire lash",
    # Water
    "water pulse", "water gun", "water shuriken", "water spout", "water pledge",
    "waterfall", "hydro pump", "hydro cannon",
    # Earth
    "earth power", "earthquake", "earth throw", "muddy water", "mud shot", "mud slap",
    # Flying
    "flying press",
    # Ancient
    "ancient power", "ancient roar",
    # Aura
    "aura sphere", "aura wheel",
    # Flash
    "flash cannon",
    # Poltergeist
    "poltergeist",
    # Sacred
    "sacred sword",
    # King
    "kings shield",
    # Last
    "last respects",
    # Wave
    "wave crash",
    # Flip
    "flip turn",
    # Scale
    "scale shot",
    # Protect
    "protect", "detect", "wide guard", "follow me", "super fang",
    # Rain
    "rain dance", "sunny day", "snarl",
    # Bulk
    "bulk up", "coil", "nasty plot", "swords dance",
    # Calm
    "calm mind", "quiver dance", "dragon dance", "shift gear", "shell smash",
    # Growth
    "growth", "autotomize", "haze", "mist", "amnesia", "barrier",
    # Reflect
    "reflect", "safeguard", "spikes", "toxic", "toxic spikes",
    "stealth rock", "sticky web", "taunt", "encore", "disable", "trick",
    "magic coat", "magic room", "wonder room", "gravity",
    # Heal
    "heal pulse", "heal bell", "healing wish", "heal order", "wish",
    "rest", "sleep talk", "roost", "milk drink", "recover", "soft-boiled",
    "absorb", "mega drain", "leech seed", "leech life", "dream eater",
    "ingrain", "aqua ring", "oblivion wing", "shore up", "strength sap",
    "morning sun", "slack off", "purify",
    # U-turn
    "u-turn", "volt switch", "flip turn", "teleport", "baton pass",
    "eject button", "eject pack", "shed tail", "beak blast",
    # Sludge
    "sludge bomb", "sludge wave",
    # Poison
    "poison jab", "poison fang", "poison tail", "poison powder",
    # Phantom
    "phantom force", "phantom bite",
    # Spirit
    "spirit break", "spirit shackle",
    # Terrain
    "terrain pulse", "electrify", "electric terrain", "grassy terrain", "misty terrain", "psychic terrain",
    # Mystical
    "mystical fire",
    # Rising
    "rising voltage",
    # Expanding
    "expanding force",
    # Triple
    "triple axel",
    # Wicked
    "wicked blow",
    # Surging
    "surging strikes",
    # Astral
    "astral barrage",
    # Glacial
    "glacial lance",
    # Bolt
    "bolt strike", "bolt beak",
    # Blue
    "blue flare", "blue flower",
    # Freeze
    "freeze-dry", "freeze shock",
}

def reconstruct_moves(raw_moves: list) -> list:
    """Reconstruct multi-word moves from split words."""
    if not raw_moves:
        return []

    moves = []
    i = 0
    while i < len(raw_moves):
        # Try 3-word combinations first
        found = False
        if i + 2 < len(raw_moves):
            triplet = f"{raw_moves[i].lower()} {raw_moves[i+1].lower()} {raw_moves[i+2].lower()}"
            if triplet in MOVE_PAIRS:
                moves.append(f"{raw_moves[i]} {raw_moves[i+1]} {raw_moves[i+2]}")
                i += 3
                found = True

        if not found and i + 1 < len(raw_moves):
            # Try 2-word combinations
            pair = f"{raw_moves[i].lower()} {raw_moves[i+1].lower()}"
            if pair in MOVE_PAIRS:
                moves.append(f"{raw_moves[i]} {raw_moves[i+1]}")
                i += 2
                found = True

        if not found:
            moves.append(raw_moves[i])
            i += 1

    # Title case
    result = []
    for m in moves:
        if m == "will-o-wisp":
            result.append("Will-O-Wisp")
        elif " " in m:
            result.append(" ".join(p.capitalize() for p in m.split()))
        else:
            result.append(m.capitalize())

    return result[:4]

def main():
    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/vgc2026_teams_detailed.json') as f:
        detailed = json.load(f)

    fixed = 0
    for team in detailed:
        if team.get("source") == "rk9":
            for p in team.get("pokemon", []):
                old_moves = p.get("moves", [])
                new_moves = reconstruct_moves(old_moves)
                if old_moves != new_moves:
                    p["moves"] = new_moves
                    fixed += 1
                    print(f"  Fixed {team['rank']} {p['species']}: {old_moves} -> {new_moves}")

    # Also fix move names in all teams to ensure proper title casing
    for team in detailed:
        for p in team.get("pokemon", []):
            moves = p.get("moves", [])
            corrected = []
            for m in moves:
                if m == "will-o-wisp":
                    corrected.append("Will-O-Wisp")
                elif " " in m:
                    corrected.append(" ".join(w.capitalize() for w in m.split()))
                else:
                    corrected.append(m.capitalize())
            p["moves"] = corrected[:4]

    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/vgc2026_teams_detailed.json', 'w') as f:
        json.dump(detailed, f, indent=2)

    print(f"Fixed {fixed} pokemon moves")
    print("Done!")

if __name__ == "__main__":
    main()