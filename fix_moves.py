#!/usr/bin/env python3
"""
Fix move names by reconstructing known multi-word Pokemon moves.
"""

# Known multi-word moves in Gen 9
MULTI_WORD_MOVES = {
    # Sleep moves
    "sleep": ["sleep powder", "sleep talk", "sleepwalk"],
    # Powder moves
    "powder": ["sleep powder", "stun powder", "poison powder", "rage powder", "cotton spore", "cotton guard", "cotton swab"],
    # Rock moves
    "rock": ["rock slide", "rock tomb", "rock throw", "rock blast", "rock polish", "rock wrecker", "rock climb"],
    # Dragon moves
    "dragon": ["dragon claw", "dragon pulse", "dragon dance", "dragon tail", "dragon breath", "dragon rage", "dragon rush", "draco meteor", "dragon energy", "dragon darts", "dragon ascent"],
    # Stomping
    "stomping": ["stomping tantrum"],
    # Dual
    "dual": ["dual wingbeat", "dual chop"],
    # Dark
    "dark": ["dark pulse", "dark void", "darkest lariat"],
    # Shadow
    "shadow": ["shadow ball", "shadow claw", "shadow sneak", "shadow bone", "shadow force"],
    # Ice
    "ice": ["ice beam", "ice punch", "ice fang", "ice shard", "ice hammer", "ice spinner"],
    # Thunder
    "thunder": ["thunder", "thunderbolt", "thunder punch", "thunder fang", "thunder wave", "thundercage", "thundershock"],
    # Solar
    "solar": ["solar beam", "solar blade", "solar flare"],
    # Focus
    "focus": ["focus blast", "focus punch", "focus energy", "focus sash"],
    # Fake
    "fake": ["fake out", "fake tears"],
    # Flare
    "flare": ["flare blitz", "flare"],
    # Swords
    "swords": ["swords dance"],
    # Cross
    "cross": ["cross chop", "cross poison"],
    # Leaf
    "leaf": ["leaf blade", "leaf storm", "leaf tornado", "leafage"],
    # Will
    "will": ["will-o-wisp", "willow"],
    # Hyper
    "hyper": ["hyper voice", "hyper beam", "hyper fang", "hyper drill"],
    # Close
    "close": ["close combat"],
    # Dire
    "dire": ["dire claw"],
    # Wide
    "wide": ["wide guard"],
    # High
    "high": ["high horsepower"],
    # Heavy
    "heavy": ["heavy slam"],
    # Light
    "light": ["light screen", "light of ruin"],
    # Calm
    "calm": ["calm mind"],
    # Trick
    "trick": ["trick room", "trick"],
    # Rage
    "rage": ["rage powder"],
    # Matcha
    "matcha": ["matcha gotcha"],
    # Drain
    "drain": ["drain punch", "drain kiss", "draining kiss"],
    # Life
    "life": ["life dew"],
    # Weather
    "weather": ["weather ball"],
    # Freeze
    "freeze": ["freeze-dry", "freeze shock"],
    # Glacial
    "glacial": ["glacial lance"],
    # Astral
    "astral": ["astral barrage"],
    # Mystical
    "mystical": ["mystical fire"],
    # Electro
    "electro": ["electro shot", "electro ball", "electroweb", "electro drift"],
    # Clang
    "clang": ["clanging scales", "clangorous soul", "clangorous soulblaze"],
    # Shell
    "shell": ["shell smash", "shell trap"],
    # Swords
    "sword": ["sword dance", "sword of mystery"],
    # Head
    "head": ["head smash", "headlong rush", "head charge"],
    # Extreme
    "extreme": ["extreme speed", "extreme evoboost"],
    # Glaciate
    "glaciate": ["glaciate"],
    # Blue
    "blue": ["blue flare", "blue flower"],
    # Bolt
    "bolt": ["bolt strike", "bolt beak", "bolt"],
    # Freezy
    "freezy": ["freeze dry"],
    # Giga
    "giga": ["giga drain", "giga impact"],
    # Brave
    "brave": ["brave bird"],
    # Air
    "air": ["air slash", "air cutter"],
    # Heat
    "heat": ["heat wave", "heat crash"],
    # Aqua
    "aqua": ["aqua jet", "aqua tail", "aqua cutter", "aqua step", "aqua ring"],
    # Scale
    "scale": ["scale shot"],
    # Spiky
    "spiky": ["spiky shield"],
    # Power
    "power": ["power gem", "power trip", "power whip", "power split"],
    # Bullet
    "bullet": ["bullet punch", "bullet seed"],
    # Iron
    "iron": ["iron head", "iron defense", "iron tail"],
    # Sucker
    "sucker": ["sucker punch"],
    # Kowtow
    "kowtow": ["kowtow cleave"],
    # Low
    "low": ["low kick", "low sweep"],
    # Quick
    "quick": ["quick attack", "quick guard"],
    # Vacuum
    "vacuum": ["vacuum wave"],
    # Blaze
    "blaze": ["blaze kick"],
    # Flare
    "flare": ["flare blitz", "flare"],
    # Parting
    "parting": ["parting shot"],
    # Throat
    "throat": ["throat chop"],
    # Dazzling
    "dazzling": ["dazzling gleam"],
    # Calm
    "calm": ["calm mind"],
    # Moon
    "moon": ["moonblast", "moonlight"],
    # Shadow
    "shadow": ["shadow ball", "shadow claw", "shadow sneak"],
    # Psychic
    "psychic": ["psychic", "psychic fangs", "psychic noise", "psychic terrain"],
    # Thunder
    "thunder": ["thunder", "thunderbolt", "thunder wave", "thunder punch"],
    # Fire
    "fire": ["fire blast", "fire punch", "fire fang", "fire spin", "fire lash"],
    # Water
    "water": ["water pulse", "water gun", "water shuriken", "water spout", "water pledge", "waterfall", "water spout"],
    # Earth
    "earth": ["earth power", "earthquake", "earth throw"],
    # Fly
    "fly": ["fly", "flying press"],
    # Thunder
    "thunder": ["thunder", "thunderbolt", "thunder wave"],
    # Iron
    "iron": ["iron head", "iron tail", "iron defense"],
    # Focus
    "focus": ["focus blast", "focus punch", "focus energy"],
    # Dragon
    "dragon": ["dragon claw", "dragon pulse", "dragon dance", "draco meteor"],
    # Fake
    "fake": ["fake out", "fake tears"],
    # Sludge
    "sludge": ["sludge bomb", "sludge wave", "sludge"],
    # Flamethrower
    "flamethrower": ["flamethrower"],
    # Flamethrower (split)
    "flame": ["flamethrower", "flame burst", "flame charge", "flame wheel"],
    # Hydro
    "hydro": ["hydro pump", "hydro cannon"],
    # Ancient
    "ancient": ["ancient power", "ancient roar"],
    # Aura
    "aura": ["aura sphere", "aura wheel"],
    # Flash
    "flash": ["flash cannon", "flash"],
    # Clanging
    "clanging": ["clanging scales"],
    # Clangorous
    "clangorous": ["clangorous soul"],
    # Trick
    "trick": ["trick room", "trick"],
    # Rage
    "rage": ["rage powder"],
    # Electro
    "electro": ["electro shot", "electro ball", "electroweb"],
    # Spiky
    "spiky": ["spiky shield"],
    # Matcha
    "matcha": ["matcha gotcha"],
    # Draining
    "draining": ["draining kiss"],
    # Life
    "life": ["life dew"],
    # Weather
    "weather": ["weather ball"],
    # Wide
    "wide": ["wide guard"],
    # Head
    "head": ["head smash", "headlong rush"],
    # Extreme
    "extreme": ["extreme speed"],
    # Brave
    "brave": ["brave bird"],
    # Giga
    "giga": ["giga drain", "giga impact"],
    # Scale
    "scale": ["scale shot"],
    # High
    "high": ["high horsepower"],
    # Heavy
    "heavy": ["heavy slam"],
    # Sucker
    "sucker": ["sucker punch"],
    # Kowtow
    "kowtow": ["kowtow cleave"],
    # Poltergeist
    "poltergeist": ["poltergeist"],
    # Sacred
    "sacred": ["sacred sword"],
    # King
    "king": ["king's shield"],
    # Glimmora
    "glimmora": ["glimmora"],  # not a move
    # Glimmorite
    "glimmorite": ["glimmorite"],
    # Last
    "last": ["last respects"],
    # Wave
    "wave": ["wave crash"],
    # Flip
    "flip": ["flip turn"],
    # Thunder
    "thunder": ["thunder", "thunderbolt"],
    # Scale
    "scale": ["scale shot"],
    # Spiky
    "spiky": ["spiky shield"],
    # Protect
    "protect": ["protect"],
    # Detect
    "detect": ["detect"],
    # Wide
    "wide": ["wide guard"],
    # Follow
    "follow": ["follow me"],
    # Super
    "super": ["super fang"],
    # Rain
    "rain": ["rain dance"],
    # Sunny
    "sunny": ["sunny day"],
    # Snarl
    "snarl": ["snarl"],
    # Bulk
    "bulk": ["bulk up"],
    # Coil
    "coil": ["coil"],
    # Nasty
    "nasty": ["nasty plot"],
    # Swords
    "swords": ["swords dance"],
    # Calm
    "calm": ["calm mind"],
    # Quiver
    "quiver": ["quiver dance"],
    # Dragon
    "dragon": ["dragon dance"],
    # Shift
    "shift": ["shift gear"],
    # Shell
    "shell": ["shell smash"],
    # Growth
    "growth": ["growth"],
    # Autotomize
    "autotomize": ["autotomize"],
    # Haze
    "haze": ["haze"],
    # Mist
    "mist": ["mist"],
    # Amnesia
    "amnesia": ["amnesia"],
    # Barrier
    "barrier": ["barrier"],
    # Reflect
    "reflect": ["reflect"],
    # Light
    "light": ["light screen"],
    # Safeguard
    "safeguard": ["safeguard"],
    # Spikes
    "spikes": ["spikes"],
    # Toxic
    "toxic": ["toxic", "toxic spikes", "toxic thread"],
    # Stealth
    "stealth": ["stealth rock"],
    # Sticky
    "sticky": ["sticky web"],
    # Taunt
    "taunt": ["taunt"],
    # Encore
    "encore": ["encore"],
    # Disable
    "disable": ["disable"],
    # Trick
    "trick": ["trick"],
    # Magic
    "magic": ["magic coat", "magic room", "magic powder"],
    # Wonder
    "wonder": ["wonder room"],
    # Gravity
    "gravity": ["gravity"],
    # Trick
    "trick": ["trick room"],
    # Heal
    "heal": ["heal pulse", "heal bell", "heal block", "healing wish", "heal order"],
    # Wish
    "wish": ["wish"],
    # Rest
    "rest": ["rest"],
    # Sleep
    "sleep": ["sleep talk"],
    # Roost
    "roost": ["roost"],
    # Milk
    "milk": ["milk drink"],
    # Recover
    "recover": ["recover", "recovery"],
    # Soft
    "soft": ["soft-boiled", "softboiled"],
    # Absorb
    "absorb": ["absorb", "mega drain", "giga drain"],
    # Leech
    "leech": ["leech seed", "leech life"],
    # Dream
    "dream": ["dream eater"],
    # Ingrain
    "ingrain": ["ingrain"],
    # Aqua
    "aqua": ["aqua ring"],
    # Oblivion
    "oblivion": ["oblivion wing"],
    # Shore
    "shore": ["shore up"],
    # Strength
    "strength": ["strength sap"],
    # Moon
    "moon": ["moonlight", "moonblast"],
    # Synthesis
    "synthesis": ["synthesis"],
    # Morning
    "morning": ["morning sun"],
    # Roost
    "roost": ["roost"],
    # Slack
    "slack": ["slack off"],
    # Shore
    "shore": ["shore up"],
    # Purify
    "purify": ["purify"],
    # Parting
    "parting": ["parting shot"],
    # U-turn
    "u-turn": ["u-turn"],
    # Volt
    "volt": ["volt switch", "volt tackle"],
    # Flip
    "flip": ["flip turn"],
    # Teleport
    "teleport": ["teleport"],
    # Baton
    "baton": ["baton pass"],
    # Eject
    "eject": ["eject button", "eject pack"],
    # Shed
    "shed": ["shed tail"],
    # Beak
    "beak": ["beak blast"],
    # Shell
    "shell": ["shell smash", "shell trap", "shell side arm"],
    # Swords
    "swords": ["swords dance"],
    # Bulk
    "bulk": ["bulk up"],
    # Coil
    "coil": ["coil"],
    # Nasty
    "nasty": ["nasty plot"],
    # Calm
    "calm": ["calm mind"],
    # Quiver
    "quiver": ["quiver dance"],
    # Dragon
    "dragon": ["dragon dance"],
    # Shift
    "shift": ["shift gear"],
    # Shell
    "shell": ["shell smash"],
    # Growth
    "growth": ["growth"],
    # Autotomize
    "autotomize": ["autotomize"],
    # Haze
    "haze": ["haze"],
    # Mist
    "mist": ["mist"],
    # Amnesia
    "amnesia": ["amnesia"],
    # Barrier
    "barrier": ["barrier"],
    # Reflect
    "reflect": ["reflect"],
    # Light
    "light": ["light screen"],
    # Safeguard
    "safeguard": ["safeguard"],
}

def reconstruct_moves(raw_moves: list) -> list:
    """Reconstruct multi-word moves from split words."""
    if not raw_moves:
        return []

    # First, try to join pairs that form known moves
    moves = []
    i = 0
    while i < len(raw_moves):
        word = raw_moves[i].lower()

        # Check if this word + next word forms a known move
        if i + 1 < len(raw_moves):
            pair = f"{word} {raw_moves[i+1].lower()}"
            # Check if this pair is a known multi-word move
            is_known = False
            for key, variants in MULTI_WORD_MOVES.items():
                if key in word or word in key:
                    for v in variants:
                        if v.startswith(pair):
                            # Found match, join them
                            moves.append(f"{raw_moves[i]} {raw_moves[i+1]}")
                            i += 2
                            is_known = True
                            break
                if is_known:
                    break
            if is_known:
                continue

        # Single word move
        moves.append(raw_moves[i])
        i += 1

    # Post-process: clean up known patterns
    cleaned = []
    for m in moves:
        # Title case the move
        m = m.strip()
        # Special cases
        if " " not in m:
            cleaned.append(m)
        else:
            # Title case each word
            parts = m.split()
            cleaned.append(" ".join(p.capitalize() for p in parts))

    return cleaned[:4]

if __name__ == "__main__":
    test_cases = [
        ["Sleep", "Powder", "Sludge", "Bomb"],
        ["Heat", "Wave", "Solar", "Beam"],
        ["Earthquake", "Rock", "Slide", "Stomping"],
        ["Fake", "Out", "Flare", "Blitz"],
        ["Moonblast", "Dazzling", "Gleam", "Calm"],
        ["Matcha", "Gotcha", "Rage", "Powder"],
        ["Rock", "Slide", "Dual", "Wingbeat", "Tailwind", "Protect"],
        ["Stomping", "Tantrum", "Dragon", "Claw", "Rock", "Slide", "Iron", "Head"],
        ["Hyper", "Voice", "Quick", "Attack", "Hyper", "Beam", "Detect"],
        ["Close", "Combat", "Dire", "Claw", "Fake", "Out", "Protect"],
        ["Kowtow", "Cleave", "Sucker", "Punch", "Low", "Kick", "Protect"],
    ]

    for tc in test_cases:
        result = reconstruct_moves(tc)
        print(f"IN:  {tc}")
        print(f"OUT: {result}")
        print()