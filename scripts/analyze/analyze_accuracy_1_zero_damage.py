#!/usr/bin/env python3
"""Phase ACCURACY-1 — Scan audits for 0-damage picks.

Read-only. For each picked action in the
audit data, check if the move is a damaging
move with v2l1 score = 0 (likely 0 damage due
to type immunity, no-effect, etc.).

Output: per-battle list of 0-damage picks
with move name, target, score, opp's HP, and
context.

NOT scoring. NOT running battles. NOT
changing source.
"""
import json
import sys
import glob
from collections import Counter, defaultdict
from pathlib import Path

# Moves that are non-damaging (always 0 base power)
# These can have 0 v2l1 score legitimately
NON_DAMAGING_MOVES = {
    # Status moves
    'protect', 'detect', 'kingsshield', 'spikyshield',
    'banefulbunker', 'obstruct', 'endure',
    # Setup moves
    'tailwind', 'trickroom', 'followme', 'ragepowder',
    'spotlight', 'swordsdance', 'nastyplot', 'calmmind',
    'dragondance', 'bulkup', 'quiverdance', 'shiftgear',
    'shellsmash', 'tailglow', 'coil', 'workup',
    'agility', 'rockpolish',
    # Stat reduction / status
    'thunderwave', 'willoowisp', 'toxic', 'willowisp',
    'haze', 'partingshot', 'fakeout', 'encore', 'taunt',
    'quash', 'hypnosis', 'disable', 'yawn', 'sleeppowder',
    'spore', 'sing', 'grasspledge', 'firepledge',
    'waterpledge', 'superpower',  # last 3 are pledges
    # Healing
    'healpulse', 'lifedew', 'pollenpuff',  # ally-targeted
    'aromatherapy', 'healbell', 'recover', 'softboiled',
    'morningsun', 'moonlight', 'synthesis', 'rest',
    'roost',
    # Field effects / screens
    'lightscreen', 'reflect', 'auroraveil',
    'rain', 'sunnyday', 'sandstorm', 'snowscape', 'hail',
    # Ally / pivot
    'partingshot', 'uturn', 'voltswitch', 'batonpass',
    # Misc utility
    'trick', 'switcheroo',
    # Fissure (OHKO) - hits 0 if target is faster or higher level
    'fissure', 'guillotine', 'horndrill', 'sheercold',
    # Counter/mirror coat etc (counter damage)
    'counter', 'mirrorcoat', 'metalburst',
    # Recharge turn
    'recharge',
    # Stockpile (raises defense/sp.def in stages)
    'stockpile',
    # Pledges (need 2 pokemon in doubles)
    'firepledge', 'waterpledge', 'grasspledge',
}


def is_damaging_move(move_id: str) -> bool:
    """Heuristic: a move is damaging if its normalized
    id is NOT in the non-damaging set."""
    mid = (move_id or '').lower().replace(' ', '').replace('-', '').replace('_', '')
    return mid not in NON_DAMAGING_MOVES


def analyze_audit(fp: str) -> list:
    """Find 0-damage picks in a single audit file."""
    cases = []
    seen_battles = set()
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            bt = r.get('battle_tag', '?')
            if bt in seen_battles:
                continue
            seen_battles.add(bt)

            for t in r.get('audit_turns', []):
                sel = t.get('v4a_final_action_keys', []) or []
                if not sel:
                    continue
                turn = t.get('turn', '?')
                ss = t.get('state_snapshot', {}) or {}
                our_active = ss.get('our_active_species', [])
                opp_active = ss.get('opp_active_species', [])
                opp_hp = ss.get('opp_active_hp_fraction', [])

                for slot_idx in (0, 1):
                    if slot_idx >= len(sel):
                        continue
                    s = sel[slot_idx]
                    if not isinstance(s, list) or len(s) < 2:
                        continue
                    move_id = s[1] if len(s) > 1 else None
                    if not move_id:
                        continue
                    if not is_damaging_move(move_id):
                        continue
                    # Get v2l1 score for this move
                    sd = t.get(
                        f'v2l1_raw_scores_slot{slot_idx}', {}
                    ) or {}
                    target = s[2] if len(s) > 2 else 0
                    key = f'move|{move_id.lower().replace(" ", "")}|{target}'
                    score = sd.get(key, None)
                    if score is None:
                        # Try with normalized target
                        score = sd.get(f'move|{move_id.lower().replace(" ", "")}|0', None)

                    # Flag EXACTLY 0-damage picks (not negative)
                    # Negative scores can occur due to
                    # recoil, ally hit penalty, etc.
                    # Only EXACT 0 indicates "no damage
                    # dealt" (immunity, no-effect, etc.)
                    if score is not None and score == 0.0:
                        cases.append({
                            'file': fp.split('/')[-1],
                            'battle': bt,
                            'turn': turn,
                            'slot': slot_idx,
                            'move': move_id,
                            'target': target,
                            'score': score,
                            'our_active': (
                                our_active[slot_idx]
                                if slot_idx < len(our_active) else None
                            ),
                            'opp_active': (
                                opp_active[target] if target is not None
                                and 0 <= target < len(opp_active)
                                else None
                            ),
                            'opp_hp': (
                                opp_hp[target] if target is not None
                                and 0 <= target < len(opp_hp)
                                else None
                            ),
                        })
    return cases


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_accuracy_1_zero_damage.py <audit.jsonl> ...")
        sys.exit(1)
    artifacts = sys.argv[1:]
    print(f"Scanning {len(artifacts)} audit files...")

    all_cases = []
    for fp in artifacts:
        cases = analyze_audit(fp)
        all_cases.extend(cases)

    print(f"\nTotal 0-damage picks found: {len(all_cases)}")
    print()
    # Categorize by move
    by_move = Counter(c['move'] for c in all_cases)
    print("By move (top 20):")
    for mv, n in by_move.most_common(20):
        print(f"  {mv}: {n}")
    print()
    # Categorize by our_active × opp_active
    by_pair = Counter()
    for c in all_cases:
        oa = c['our_active'] or '?'
        op = c['opp_active'] or '?'
        by_pair[(oa, op)] += 1
    print("By attacker→defender (top 20):")
    for (oa, op), n in by_pair.most_common(20):
        print(f"  {oa} → {op}: {n}")
    print()
    # Sample cases
    print("Sample 10 cases:")
    for c in all_cases[:10]:
        print(
            f"  {c['battle']} T{c['turn']} slot{c['slot']}: "
            f"{c['our_active']} → {c['opp_active']} "
            f"move={c['move']} target={c['target']} "
            f"score={c['score']} opp_hp={c['opp_hp']}"
        )

    # Write JSON output
    out_path = Path("/tmp/phaseACCURACY1_zero_damage.json")
    with open(out_path, 'w') as f:
        json.dump({
            'n_total': len(all_cases),
            'by_move': dict(by_move),
            'by_pair': {f'{k[0]}→{k[1]}': v for k, v in by_pair.items()},
            'sample': all_cases[:20],
        }, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
