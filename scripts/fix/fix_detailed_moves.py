#!/usr/bin/env python3
"""
Reconstruct moves in the detailed teams file.
"""

import json

# Extended known multi-word moves dictionary
MOVE_PAIRS = {
    "sleep powder", "stun powder", "poison powder", "rage powder", "cotton guard",
    "rock slide", "rock tomb", "rock throw", "rock blast", "rock polish", "rock wrecker",
    "dragon claw", "dragon pulse", "dragon dance", "dragon tail", "draco meteor", "dragon darts",
    "stomping tantrum",
    "dual wingbeat", "dual chop",
    "dark pulse", "dark void", "darkest lariat",
    "shadow ball", "shadow claw", "shadow sneak", "shadow bone", "shadow force",
    "ice beam", "ice punch", "ice fang", "ice shard", "ice hammer", "ice spinner",
    "thunderbolt", "thunder punch", "thunder fang", "thunder wave", "thundercage", "thundershock",
    "solar beam", "solar blade",
    "focus blast", "focus punch", "focus energy",
    "fake out", "fake tears",
    "flare blitz",
    "swords dance",
    "cross chop", "cross poison",
    "leaf blade", "leaf storm",
    "will-o-wisp",
    "hyper voice", "hyper beam", "hyper fang",
    "close combat",
    "dire claw",
    "wide guard",
    "high horsepower",
    "heavy slam",
    "light screen", "light of ruin",
    "calm mind",
    "trick room",
    "matcha gotcha",
    "drain punch", "drain kiss", "draining kiss",
    "life dew",
    "weather ball",
    "electro shot", "electro ball", "electroweb", "electro drift",
    "clanging scales", "clangorous soul",
    "shell smash",
    "head smash", "headlong rush",
    "extreme speed",
    "giga drain", "giga impact",
    "brave bird",
    "air slash",
    "heat wave", "heat crash",
    "aqua jet", "aqua tail", "aqua cutter", "aqua step", "aqua ring",
    "scale shot",
    "spiky shield",
    "power gem", "power trip", "power whip",
    "bullet punch", "bullet seed",
    "iron head", "iron defense", "iron tail",
    "sucker punch",
    "kowtow cleave",
    "low kick", "low sweep",
    "quick attack", "quick guard",
    "vacuum wave",
    "blaze kick",
    "parting shot",
    "throat chop",
    "dazzling gleam",
    "moonblast", "moonlight",
    "psychic",
    "thunder",
    "fire blast", "fire punch", "fire fang", "fire spin", "fire lash",
    "water pulse", "water shuriken", "water spout", "waterfall",
    "earth power", "earthquake",
    "flying press",
    "ancient power",
    "aura sphere", "aura wheel",
    "flash cannon",
    "poltergeist",
    "sacred sword",
    "king's shield",
    "last respects",
    "wave crash",
    "flip turn",
    "scale shot",
    "protect", "detect", "wide guard", "follow me", "super fang",
    "rain dance", "sunny day", "snarl",
    "bulk up", "coil", "nasty plot", "swords dance",
    "quiver dance", "dragon dance", "shift gear", "shell smash",
    "growth", "autotomize", "haze", "mist", "amnesia", "barrier",
    "reflect", "safeguard", "spikes", "toxic", "toxic spikes",
    "stealth rock", "sticky web", "taunt", "encore", "disable", "trick",
    "magic coat", "magic room", "wonder room", "gravity",
    "heal pulse", "heal bell", "healing wish", "heal order", "wish",
    "rest", "sleep talk", "roost", "milk drink", "recover", "soft-boiled",
    "absorb", "mega drain", "leech seed", "leech life", "dream eater",
    "ingrain", "aqua ring", "oblivion wing", "shore up", "strength sap",
    "morning sun", "slack off", "purify",
    "u-turn", "volt switch", "flip turn", "teleport", "baton pass",
    "eject button", "eject pack", "shed tail", "beak blast",
    # ADDITIONAL MISSING:
    "sludge bomb", "sludge wave", "sludge",
    "muddy water", "mud shot", "mud slap",
    "rock tomb", "rock blast",
    "dragon tail", "draco meteor",
    "phantom force", "phantom bite",
    "spirit break", "spirit shackle",
    "thunder cage",
    "terrain pulse",
    "mystical fire",
    "rising voltage",
    "expanding force",
    "triple axel",
    "wicked blow",
    "surging strikes",
    "astral barrage",
    "glacial lance",
    "wicked blow",
    "surging strikes",
}

def reconstruct_moves(raw_moves: list) -> list:
    """Reconstruct multi-word moves from split words."""
    if not raw_moves:
        return []

    # Check if moves already look correct
    has_spaces = any(" " in m for m in raw_moves)
    if has_spaces and len(raw_moves) <= 4:
        # Already mostly correct, just title case
        result = []
        for m in raw_moves:
            if m == "will-o-wisp":
                result.append("Will-O-Wisp")
            elif " " in m:
                result.append(" ".join(p.capitalize() for p in m.split()))
            else:
                result.append(m.capitalize())
        return result[:4]

    # Otherwise, try to join pairs
    moves = []
    i = 0
    while i < len(raw_moves):
        if i + 1 < len(raw_moves):
            pair = f"{raw_moves[i].lower()} {raw_moves[i+1].lower()}"
            if pair in MOVE_PAIRS:
                moves.append(f"{raw_moves[i]} {raw_moves[i+1]}")
                i += 2
                continue
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
    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_teams_detailed.json') as f:
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

    # Also fix move names in all teams to ensure proper title casing
    for team in detailed:
        for p in team.get("pokemon", []):
            moves = p.get("moves", [])
            corrected = []
            for m in moves:
                if m == "will-o-wisp":
                    corrected.append(m)
                elif " " in m:
                    corrected.append(" ".join(p.capitalize() for p in m.split()))
                else:
                    corrected.append(m.capitalize())
            p["moves"] = corrected[:4]

    with open('/home/phurin/Program/Showdown_AI/pokemon-showdown-ai/data/vgc2026_teams_detailed.json', 'w') as f:
        json.dump(detailed, f, indent=2)

    print(f"Fixed {fixed} teams' moves")
    print("Done!")

if __name__ == "__main__":
    main()